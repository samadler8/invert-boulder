/**
     * Atmospheric Model & Coordinates Configuration
     * Location reference for the Boulder HRRR forecast (model features use KBDU)
     */
    const BOULDER_LAT = 40.0150;
    const BOULDER_LON = -105.2705;

    // Landmark Altitudes in ft MSL
    const ELEV_BOULDER = 5400;
    const ELEV_FLATIRON = 7258;
    const CURRENT_SCENIC_VERSION = 'hrrr-scenic-suitability-v3-precise-elevations';
    const ELEV_GREEN_MT = 8133;

    // State object
    let leafletTransectMap = null;
    let leafletTransectLayers = null;
    let transectMetric = 'low_cloud_pct';
    let transectSelected = 'green';
    let transectRefreshPolling = false;
    let solarTimesCache = new Map();
    let explorerPlayback = null;
    let solarLoading = new Set();
    let state = {
      isLive: true,
      rawHourly: null,
      daysData: [],           // issued-run hours (<40h)
      selectedDayIdx: 1,      // Default 1 = Tomorrow
      selectedHourIdx: 6,     // Default to peak hour of selected day
      chartMode: 'scenic' // scenic Green Mountain, low cloud index, or cloud cover
    };

    /**
     * Presets Data Structure for Instant Testing
     */
    const PRESETS = {
      epic: generateSyntheticDay("Classic Inversion (7,258' & 8,133' Above Fog)", 6700, 92, 2.0, 7.5, 95, 80),
      high: generateSyntheticDay("High Fog Deck (Only 8,133' Peak Above)", 7600, 84, 1.0, 4.0, 96, 60),
      socked: generateSyntheticDay("Deep Fog Deck (All 3 Socked In)", 8400, 76, 0.5, -2.0, 98, 40),
      clear: generateSyntheticDay("Bluebird / Downslope (No Inversion)", 5400, 12, 14.0, 3.0, 30, 270)
    };

    /**
     * Window Load Initializer
     */
    window.onload = function() {
      // Sun times remain useful even before an HRRR forecast is downloaded.
      const todayBoulder = new Date().toLocaleDateString('sv-SE', {timeZone:'America/Denver'});
      renderSolarForDay({dateStr:todayBoulder});
      fetchWeatherData();
      loadForecastHistory();
      loadForecastWindow();
    };

    /**
     * Fetch live HRRR-derived heuristic indices
     */
    async function fetchWeatherData(refresh = false) {
      const refreshIcon = document.getElementById('refreshIcon');
      refreshIcon.classList.add('fa-spin');
      try {
        const response = await fetch(`/api/forecast?refresh=${refresh}`);
        const payload = await response.json();
        if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'Forecast API error');
        state.savedDays = convertForecast(payload.hours);
        state.daysData = state.savedDays;
        state.isLive = true;
        state.modelInfo = payload.model;
        state.selectedDayIdx = Math.min(1, state.daysData.length - 1);
        state.selectedHourIdx = state.daysData[state.selectedDayIdx].peakHour;
        document.getElementById('apiStatusText').textContent = payload.model.ml_available
          ? 'Scenic + low-cloud indices' : 'Scenic + low-cloud indices';
        document.getElementById('statusBadge').classList.remove('hidden');
        document.getElementById('modelCaveat').textContent = payload.heuristic.warning + ' ' + payload.model.warning;
        setActivePresetBtn('live');
        renderSelectedDay();
      } catch (error) {
        console.error('Forecast unavailable:', error);
        document.getElementById('statusBadge').classList.remove('hidden');
        document.getElementById('apiStatusText').textContent = 'Forecast unavailable';
        document.getElementById('modelCaveat').textContent = String(error.message);
        document.getElementById('verdictTitle').textContent = 'HRRR forecast cache unavailable';
        document.getElementById('verdictDesc').textContent = String(error.message);
        document.getElementById('probPercent').textContent = '--/100';
        document.getElementById('heuristicComponents').textContent = 'No live forecast data available.';
        document.getElementById('scenicDetails').textContent = 'No live scenic diagnostic available.';
        document.getElementById('scenicScore').textContent = '—';
        document.getElementById('modeledCloudTop').textContent = '';
        // Never replace a failed live forecast with a seemingly real demo.
        state.isLive = true;
        state.daysData = [];
        document.getElementById('forecastStrip').textContent = 'No live forecast available. Check the model training steps in README.';
        document.getElementById('hourlyChartSVG').innerHTML = '';
        document.getElementById('landmarkForecasts').textContent = 'No valid elevation predictions available.';
        document.getElementById('cloudBaseSummary').textContent = '';
        document.getElementById('explorerNotice').textContent = 'No usable live forecast cache. The schematic does not substitute synthetic weather.';
        document.getElementById('explorerSlider').disabled = true;
        document.getElementById('forecastMetricsExtended').textContent = 'Forecast measurements unavailable.';
        renderFoothillsTransect({});
        document.getElementById('fogRect').setAttribute('opacity','0');
        document.getElementById('fogTopPuffs').setAttribute('opacity','0');
        document.getElementById('breakoutLineGroup').style.display = 'none';
        document.getElementById('clearSkyNotice').style.display = 'block';
        document.querySelector('#clearSkyNotice text').textContent = 'LIVE FORECAST UNAVAILABLE';
        ['txtBadgeBoulder','txtBadgeFlatiron','txtBadgeGreenMt'].forEach(id=>{
          document.getElementById(id).textContent = 'UNVERIFIED';
        });
      } finally {
        refreshIcon.classList.remove('fa-spin');
      }
    }

    /** Render the archived calculation, using plain DOM text for forecast data. */
    function renderHeuristicEvidence(node, prediction, compact = false) {
      node.replaceChildren();
      const factorRows = prediction?.heuristic_breakdown;
      if (!Array.isArray(factorRows) || !factorRows.length) {
        const old = document.createElement('p');
        old.className = 'text-xs text-amber-200';
        old.textContent = 'This older saved forecast predates detailed input archiving. Its original score and available factor summaries are preserved; missing raw readings cannot be reconstructed from the snapshot.';
        node.appendChild(old);
        const prior = prediction?.heuristic_components || {};
        Object.entries(prior).forEach(([name, factor]) => {
          const line = document.createElement('p');
          line.className = 'text-xs text-slate-400';
          line.textContent = `${name.replaceAll('_', ' ')}: ${factor}/100`;
          node.appendChild(line);
        });
        return;
      }
      const total = document.createElement('p');
      total.className = 'text-xs text-cyan-200 font-semibold';
      total.textContent = `Weighted points: ${prediction.heuristic_unrounded_score.toFixed(2)} → ${prediction.heuristic_score}/100 (rounded). This is NOT a probability.`;
      node.appendChild(total);

      factorRows.forEach((factor) => {
        const item = document.createElement('div');
        item.className = 'rounded-xl border border-slate-700/80 bg-slate-950/60 p-3 space-y-1';
        const heading = document.createElement('div');
        heading.className = 'flex flex-wrap items-center justify-between gap-2 text-xs';
        const label = document.createElement('strong');
        label.className = 'text-slate-100';
        label.textContent = factor.label;
        const points = document.createElement('span');
        points.className = 'font-mono font-bold text-cyan-300';
        points.textContent = `${factor.weighted_points.toFixed(1)} / ${factor.max_points.toFixed(0)} pts`;
        heading.append(label, points);
        const readings = document.createElement('p');
        readings.className = 'text-xs text-slate-300';
        readings.textContent = (factor.readings || []).map((reading) => {
          const v = reading.value;
          const rounded = v == null ? 'unavailable' :
            (Math.abs(v) >= 1000 ? Number(v).toLocaleString('en-US', {maximumFractionDigits: 1}) : Number(v).toFixed(1));
          return `${reading.label}: ${rounded}${v == null ? '' : ' ' + reading.unit}`;
        }).join(' · ');
        const explanation = document.createElement('p');
        explanation.className = 'text-[11px] text-slate-400';
        explanation.textContent = `Factor ${factor.factor_score.toFixed(1)}/100 · weight ${factor.weight_pct}%${factor.has_missing_readings ? ' · Missing input: neutral 50/100 fallback used for that input' : ''}`;
        item.append(heading, readings, explanation);
        if (!compact) {
          const rule = document.createElement('p');
          rule.className = 'text-[11px] text-slate-500';
          rule.textContent = factor.scoring_rule;
          item.appendChild(rule);
        }
        node.appendChild(item);
      });
      if (!compact && Array.isArray(prediction.heuristic_extra_readings)) {
        const more = document.createElement('details');
        more.className = 'text-xs text-slate-400 border-t border-slate-700 pt-2';
        const heading = document.createElement('summary');
        heading.className = 'cursor-pointer font-semibold text-slate-300';
        heading.textContent = 'Additional HRRR fields (not directly counted in the index)';
        more.appendChild(heading);
        prediction.heuristic_extra_readings.forEach((reading) => {
          const item = document.createElement('p');
          item.className = 'py-1';
          item.textContent = `${reading.label}: ${reading.value == null ? 'unavailable' : Number(reading.value).toLocaleString('en-US', {maximumFractionDigits: 1}) + ' ' + reading.unit}`;
          more.appendChild(item);
        });
        node.appendChild(more);
      }
      const source = prediction.forecast_source;
      if (source) {
        const box = document.createElement('div');
        box.className = 'border-t border-slate-700 pt-3 space-y-1 text-xs';
        const context = document.createElement('p');
        context.className = 'text-slate-300';
        context.textContent = `${source.model} · ${source.requested_latitude}, ${source.requested_longitude} · HRRR run ${source.run_utc} · lead ${source.forecast_lead_hours}h`;
        box.appendChild(context);
        const links = [
          ['Original NOAA surface-field inventory', source.surface_inventory_url],
          ['Original NOAA pressure-field inventory', source.pressure_inventory_url],
          ['NOAA HRRR model information', source.model_documentation_url],
        ];
        const linkRow = document.createElement('div');
        linkRow.className = 'flex flex-wrap gap-x-4 gap-y-2';
        links.forEach(([name, href]) => {
          if (typeof href !== 'string' || !href.startsWith('https://')) return;
          const a = document.createElement('a');
          a.href = href;
          a.target = '_blank';
          a.rel = 'noopener noreferrer';
          a.className = 'text-cyan-300 underline underline-offset-2 hover:text-cyan-100';
          a.textContent = name;
          linkRow.appendChild(a);
        });
        box.appendChild(linkRow);
        const note = document.createElement('p');
        note.className = 'text-[11px] text-slate-500';
        note.textContent = source.important_note;
        box.appendChild(note);
        node.appendChild(box);
      }
    }

    /** Compare *issued model forecasts* to an independent airport METAR report. */
    function renderObservedAtEvent(node, obs) {
      if (!node) return;
      node.replaceChildren();
      const p = document.createElement('p');
      p.className = 'text-sm text-slate-300';
      if (!obs) {
        p.textContent = 'No locally cached KBDU observation for this target hour. Click “Refresh actual airport report” to retrieve the nearest-hour IEM/METAR report. No report does not mean clear weather.';
        node.appendChild(p);
        return;
      }
      const label = (v, yes, no) => v === 1 ? yes : v === 0 ? no : 'Unreported / unknown';
      p.textContent = `Airport low ceiling (≤1,000 ft AGL): ${label(obs.observed_low_ceiling, 'Reported', 'Not reported')} · Fog-like event: ${label(obs.observed_fog, 'Reported', 'Not reported')}.`;
      const detail = document.createElement('p');
      detail.className = 'text-xs text-slate-400 mt-1';
      const f = x => x == null ? 'not reported' : Number(x).toLocaleString('en-US', {maximumFractionDigits: 1});
      detail.textContent = `Visibility: ${f(obs.visibility_miles)} miles · Lowest reported ceiling: ${f(obs.observed_cloud_base_ft_msl)} ft MSL · ${obs.source}. Reports are rounded to nearest hour. No direct cloud-top or mountain visibility measurement.`;
      node.append(p, detail);
    }

    /** Forecast *revision* across different HRRR issued runs, not statistical error bars. */
    function renderVintageDisagreement(node, comparisons) {
      if (!node) return;
      node.replaceChildren();
      const title = document.createElement('h4');
      title.className = 'font-semibold text-sm text-white';
      title.textContent = 'Did the HRRR forecasts agree?';
      node.appendChild(title);
      const data = comparisons.filter(c => c.forecast?.scenic_indicators).map(c => ({
        hour: c.hours_before_event,
        mid: c.forecast.scenic_indicators.mid_cloud_cover_pct,
        high: c.forecast.scenic_indicators.high_cloud_cover_pct,
        low: c.forecast.scenic_indicators.low_cloud_cover_pct,
      }));
      const lines = [];
      for (const [key, label] of [['low', 'Low'], ['mid', 'Middle'], ['high', 'High']]) {
        const values = data.map(r => Number(r[key])).filter(x => Number.isFinite(x));
        if (values.length < 2) continue;
        const min = Math.min(...values), max = Math.max(...values);
        const spread = max - min;
        lines.push(`${label} cloud: ${Math.round(min)}–${Math.round(max)}% (spread ${Math.round(spread)} percentage points)`);
      }
      const p = document.createElement('p');
      p.className = 'text-xs text-slate-300';
      p.textContent = lines.length ? lines.join(' · ') : 'At least two forecast vintages with full cloud-layer data are needed.';
      node.appendChild(p);
      const upper = data.filter(d => Number.isFinite(Number(d.mid)) && Number.isFinite(Number(d.high)));
      if (upper.length >= 2) {
        const mid = upper.map(r => Number(r.mid)), high = upper.map(r => Number(r.high));
        const dramatic = Math.max(Math.max(...mid) - Math.min(...mid), Math.max(...high) - Math.min(...high)) >= 40;
        const note = document.createElement('p');
        note.className = dramatic ? 'text-xs text-amber-200' : 'text-xs text-emerald-200';
        note.textContent = dramatic
          ? 'Large upper-cloud forecast revision. Scenic scores are sensitive to changing middle/high cloud predictions—plan conservatively.'
          : 'Upper-cloud forecasts were relatively consistent across these saved runs.';
        node.appendChild(note);
      }
      const caveat = document.createElement('p');
      caveat.className = 'text-[11px] text-slate-500';
      caveat.textContent = 'These ranges measure forecast-to-forecast changes at one HRRR grid cell, NOT verified accuracy, probabilities, or neighborhood variation.';
      node.appendChild(caveat);
    }

    /** Refresh independent station observations on demand, never on page load. */
    async function refreshSelectedObservation() {
      const button = document.getElementById('historyObserveButton');
      const status = document.getElementById('historyObservationStatus');
      const target = document.getElementById('historyTimeSelect')?.value;
      if (!target || !button || !status) return;
      button.disabled = true;
      status.textContent = 'Retrieving independent airport METAR reports for this UTC date…';
      try {
        const res = await fetch('/api/history/observation/refresh', {
          method:'POST', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({event_utc:target})
        });
        const task = await res.json();
        if (!res.ok) throw new Error(task.detail || 'Observation refresh unavailable');
        for (let i = 0; i < 80; i++) {
          const response = await fetch(`/api/history/reconstruct/status?job_id=${encodeURIComponent(task.id)}`);
          const value = await response.json();
          if (!response.ok) throw new Error(value.detail || 'Status unavailable');
          if (value.state === 'complete') {
            const result = (value.progress || [])[0] || {};
            if (result.status === 'error') throw new Error(result.message);
            await loadForecastHistory(target);
            status.textContent = `IEM returned ${result.new_reports || 0} station hours. If the target is still unavailable, no matching station report was returned.`;
            return;
          }
          await new Promise(resolve => setTimeout(resolve, 1500));
        }
        status.textContent = 'Still downloading; reload the hour after it completes.';
      } catch (err) {
        status.textContent = `Observation refresh failed: ${err.message}`;
      } finally {
        button.disabled = false;
      }
    }

    /** Inspect several as-of vintages for the same past weather hour. */
    async function loadForecastHistory(target = null) {
      const dropdown = document.getElementById('historyTimeSelect');
      const cards = document.getElementById('historyCards');
      const status = document.getElementById('historyStatus');
      const provenance = document.getElementById('historyProvenance');
      const observedBox = document.getElementById('historyObserved');
      const disagreementBox = document.getElementById('historyDisagreement');
      const fill = document.getElementById('historyFillButton');
      if (!dropdown || !cards) return;
      const selected = target || dropdown.value || '';
      const url = '/api/history' + (selected ? `?event_utc=${encodeURIComponent(selected)}` : '');
      status.textContent = 'Loading saved historical forecast vintages…';
      try {
        const response = await fetch(url);
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'History API unavailable');
        const fmt = (iso) => new Intl.DateTimeFormat('en-US', {
          timeZone: 'America/Denver', month: 'short', day: 'numeric',
          hour: 'numeric', minute: '2-digit', timeZoneName: 'short'
        }).format(new Date(iso));
        dropdown.replaceChildren();
        if (!data.event_times_utc.length) {
          dropdown.add(new Option('No past target hours recorded yet', ''));
          dropdown.disabled = true;
          if (fill) fill.disabled = true;
          cards.replaceChildren();
          if (observedBox) observedBox.textContent = 'Choose a past hour to inspect actual station observations.';
          if (disagreementBox) disagreementBox.replaceChildren();
          status.textContent = 'No past-hour history available yet. Run quicklook once to populate the past timeline.';
          provenance.textContent = data.note;
          return;
        }
        dropdown.disabled = false;
        data.event_times_utc.forEach((hour) => dropdown.add(new Option(fmt(hour), hour)));
        if (data.selected_event_utc) dropdown.value = data.selected_event_utc;
        const available = data.comparisons.filter(c => c.forecast !== null).length;
        const outdated = data.comparisons.filter(c => c.forecast !== null && c.needs_refresh).length;
        const missing = data.comparisons.filter(c => c.forecast === null).length;
        const actionable = missing + outdated;
        status.textContent = `${fmt(data.selected_event_utc)} · ${available}/${data.comparisons.length} cutoffs saved` +
          (outdated ? ` · ${outdated} older reconstruction(s) missing current scenic details` : '') +
          ` · ${data.event_times_utc.length} past target hours recorded`;
        if (fill) {
          fill.disabled = actionable === 0;
          fill.textContent = actionable === 0
            ? 'All five forecast cutoffs up to date'
            : `Fetch / update ${actionable} forecast cutoff(s)`;
          fill.classList.toggle('opacity-50', fill.disabled);
        }
        cards.replaceChildren();
        const number = (x, unit = '') => x == null || !Number.isFinite(Number(x))
          ? '—' : `${Number(x).toLocaleString('en-US', {maximumFractionDigits:1})}${unit}`;
        const fmtScore = (x) => x == null ? '—' : `${Math.round(x)}/100`;
        const mk = (tag, cls, value) => {
          const el = document.createElement(tag);
          el.className = cls;
          el.textContent = value;
          return el;
        };
        renderObservedAtEvent(observedBox, data.observation);
        renderVintageDisagreement(disagreementBox, data.comparisons);
        for (const comparison of data.comparisons) {
          const card = document.createElement('article');
          card.className = 'bg-slate-900/90 border border-slate-700 rounded-2xl p-4 space-y-3';
          const top = mk('div', 'flex flex-wrap justify-between items-center gap-2', '');
          top.append(
            mk('h4', 'text-base font-bold text-white', comparison.hours_before_event === 0 ? 'T−0 · latest available HRRR at event' : `T−${comparison.hours_before_event} hours`),
            mk('span', 'text-xs text-slate-400', `As-of cutoff ${fmt(comparison.as_of_utc)}`)
          );
          card.appendChild(top);
          const p = comparison.forecast;
          if (!p) {
            card.appendChild(mk('p', 'text-sm text-amber-200', 'No forecast saved for this cutoff.'));
            card.appendChild(mk('p', 'text-xs text-slate-400', 'Use “Fill missing forecast cutoffs” above to retrieve this issued HRRR forecast only.'));
            cards.appendChild(card);
            continue;
          }
          const badges = mk('div', 'grid grid-cols-3 gap-2', '');
          const scores = [
            ['Green Mt', p.scenic_heuristic_score, 'text-amber-200'],
            ['1st Flatiron', p.scenic_flatiron_score, 'text-sky-200'],
            ['Boulder low cloud', p.heuristic_score, 'text-cyan-200'],
          ];
          for (const [label, value, color] of scores) {
            const tile = mk('div', 'bg-slate-950/65 border border-slate-800 rounded-lg p-2 space-y-1', '');
            tile.append(mk('p', 'text-[11px] text-slate-400', label),
                        mk('p', `text-lg font-extrabold font-mono ${color}`, fmtScore(value)));
            badges.appendChild(tile);
          }
          card.appendChild(badges);
          card.appendChild(mk('p', 'text-xs text-slate-300', p.scenic_heuristic_reason || 'Scenic outcome not resolved in this saved forecast.'));
          if (p.scenic_version && p.scenic_version !== CURRENT_SCENIC_VERSION) {
            card.appendChild(mk('p', 'text-xs text-amber-200',
              'Original archived scenic version: earlier target-elevation assumptions. This snapshot has not been silently rewritten for the updated 7,258 ft / 8,133 ft summits.'));
          }
          if (comparison.needs_refresh) {
            card.appendChild(mk('p', 'text-xs text-amber-200',
              'This is a legacy reconstructed snapshot: upper-cloud and summit evidence was not archived. Use “Fetch / update” to recalculate this forecast from archived HRRR data. The original snapshot will be retained.'));
          }
          const indicators = p.scenic_indicators || {};
          const measurements = [
            ['Low clouds', number(indicators.low_cloud_cover_pct ?? p.lowClouds, '%')],
            ['Middle clouds', number(indicators.mid_cloud_cover_pct, '%')],
            ['High clouds', number(indicators.high_cloud_cover_pct, '%')],
            ['Surface humidity', number(p.rh, '%')],
            ['Near-surface ΔT', number(p.tempDelta, '°C')],
            ['10 m wind', number(p.windSpeed, ' mph')],
            ['RH at Green Mt', number(indicators.green_rh_at_summit_pct, '%')],
            ['RH at 7,400 ft', number(indicators.green_rh_at_7400ft_pct, '%')],
            ['Modeled cloud base', number(indicators.forecast_cloud_base_ft_msl, ' ft')],
          ];
          const grid = mk('div', 'grid grid-cols-2 sm:grid-cols-3 gap-x-3 gap-y-2 border-t border-slate-700 pt-3', '');
          for (const [label, value] of measurements) {
            const tile = mk('div', 'space-y-0.5', '');
            tile.append(mk('p', 'text-[11px] text-slate-400', label),
                        mk('p', 'text-sm font-semibold text-slate-200', value));
            grid.appendChild(tile);
          }
          card.appendChild(grid);
          const neighborhood = p.scenic_spatial_uncertainty;
          if (neighborhood?.available) {
            const range = neighborhood.cloud_spread_pct || {};
            card.appendChild(mk('p', neighborhood.classification === 'high'
              ? 'text-xs text-amber-200' : 'text-xs text-slate-300',
              `Nearby-grid spread (${neighborhood.count} points): middle-cloud ${number(range.mid_cloud_pct, '%')}, high-cloud ${number(range.high_cloud_pct, '%')} · ${neighborhood.classification} local spatial disagreement (diagnostic only).`));
          } else {
            card.appendChild(mk('p', 'text-xs text-slate-500',
              'Nearby-grid samples unavailable in this saved forecast.'));
          }
          card.appendChild(mk('p', 'text-xs text-slate-300',
            `HRRR run ${fmt(p.run_utc)} · model F${p.lead_hours} · forecast availability at cutoff assumed for reconstructions (2h lag)`));
          if (comparison.hours_before_event === 0) {
            card.appendChild(mk('p', 'text-xs text-emerald-200',
              'This is still a model forecast: latest plausibly issued by the event time, NOT an observed weather report or necessarily a lead-0 analysis.'));
          }
          card.appendChild(mk('p', 'text-xs font-semibold ' +
            (p.origin === 'captured' ? 'text-emerald-300' : 'text-amber-300'),
            p.origin === 'captured'
              ? `Actually captured by this app: ${fmt(p.captured_at_utc)}`
              : `Reconstructed after the event · heuristic version: ${p.heuristic_version || 'unknown'}`));
          card.appendChild(mk('p', 'text-xs text-slate-400', p.ml_probability == null
            ? 'ML archived'
            : `Legacy ML (historical only): ${Math.round(p.ml_probability * 100)}% (${p.event || 'airport event'})`));
          const detail = document.createElement('details');
          detail.className = 'border-t border-slate-700 pt-2';
          detail.appendChild(mk('summary', 'text-xs text-cyan-300 cursor-pointer',
            'Full heuristic breakdown, raw forecast readings and NOAA links'));
          const evidence = mk('div', 'space-y-2 pt-3', '');
          renderHeuristicEvidence(evidence, p, false);
          detail.appendChild(evidence);
          card.appendChild(detail);
          cards.appendChild(card);
        }
        provenance.textContent = data.note;
      } catch (error) {
        status.textContent = `Could not read history: ${error.message}`;
        cards.replaceChildren();
      }
    }

    /** Explicit, bounded download: only the chosen past hour's missing cutoffs. */
    async function reconstructSelectedHistory() {
      const dropdown = document.getElementById('historyTimeSelect');
      const button = document.getElementById('historyFillButton');
      const progress = document.getElementById('historyFillProgress');
      const target = dropdown?.value;
      if (!target || !button || !progress) return;
      button.disabled = true;
      let completed = false;
      progress.textContent = 'Starting selected-hour HRRR reconstruction (up to five as-of forecasts)…';
      try {
        const response = await fetch('/api/history/reconstruct', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({event_utc: target})
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || 'Could not start reconstruction');
        const id = result.id;
        for (let attempt = 0; attempt < 240; attempt++) {
          const poll = await fetch(`/api/history/reconstruct/status?job_id=${encodeURIComponent(id)}`);
          const state = await poll.json();
          if (!poll.ok) throw new Error(state.detail || 'Reconstruction status unavailable');
          const finished = state.progress || [];
          progress.textContent = `Retrieving historical HRRR: ${finished.length}/${state.total_offsets} cutoffs checked` +
            (finished.some(x => x.status === 'error') ? ' · some downloads failed' : '');
          if (state.state === 'complete') {
            const errors = finished.filter(x => x.status === 'error');
            await loadForecastHistory(target);
            await loadForecastWindow();
            progress.textContent = errors.length
              ? `Finished with ${errors.length} error(s). Open the missing cards or retry; previous downloads remain saved. ` +
                errors.map(e => `T−${e.offset_hours}: ${e.message}`).join(' · ')
              : 'Comparison updated. Available cutoffs are now shown above; reconstructed values are not original website snapshots.';
            completed = true;
            return;
          }
          await new Promise(resolve => setTimeout(resolve, 1500));
        }
        progress.textContent = 'Still processing. You can revisit this hour and reload saved history later.';
      } catch (error) {
        progress.textContent = `Could not fill missing forecasts: ${error.message}`;
      } finally {
        if (!completed) button.disabled = false;
      }
    }


    /** ±48h visual explorer. Reads saved data; never initiates unbounded NOAA downloads. */
    async function loadForecastWindow() {
      const status = document.getElementById('quicklookStatus');
      const pastNode = document.getElementById('quicklookPast');
      const futureNode = document.getElementById('quicklookFuture');
      if (!status || !pastNode || !futureNode) return;
      status.textContent = 'Reading local 48-hour forecast cache and historical ledger…';
      try {
        const response = await fetch('/api/window');
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || 'Forecast window unavailable');
        const when = (stamp) => new Intl.DateTimeFormat('en-US', {
          timeZone: 'America/Denver', month: 'short', day: 'numeric',
          hour: 'numeric', minute: '2-digit', timeZoneName: 'short'
        }).format(new Date(stamp));
        const score = (value) => value == null ? '—' : `${Math.round(value)}/100`;
        const draw = (node, entries, isPast) => {
          node.replaceChildren();
          if (!entries.length) {
            const empty = document.createElement('p');
            empty.className = 'text-xs text-amber-200 col-span-full';
            empty.textContent = isPast
              ? 'No eligible past forecasts. Run python -m scripts.quicklook to reconstruct issued HRRR vintages.'
              : (payload.future_error || 'No current future forecasts saved. Run python -m scripts.quicklook.');
            node.appendChild(empty);
            return;
          }
          for (const item of entries) {
            const card = document.createElement('button');
            card.type = 'button';
            card.className = 'text-left rounded-xl bg-slate-950/70 border border-slate-700 p-3 space-y-1 hover:border-cyan-400 focus:outline-none focus:ring-2 focus:ring-cyan-400';
            const title = document.createElement('p');
            title.className = 'text-xs font-semibold text-slate-100';
            title.textContent = when(item.timestamp);
            const scenic = document.createElement('p');
            scenic.className = 'text-lg font-bold font-mono ' + (isPast ? 'text-amber-200' : 'text-cyan-200');
            scenic.textContent = `Green Mt: ${score(item.scenic_heuristic_score)}`;
            const low = document.createElement('p');
            low.className = 'text-xs text-slate-300';
            low.textContent = `Low cloud: ${score(item.heuristic_score)}`;
            const source = document.createElement('p');
            source.className = 'text-[10px] text-slate-400';
            source.textContent = isPast
              ? (item.origin === 'captured' ? 'Captured before event' : 'Reconstructed later')
              : `HRRR F${item.lead_hours} · ${when(item.run_utc)}`;
            card.append(title, scenic, low, source);
            if (item.ml_probability != null) {
              const ml = document.createElement('p');
              ml.className = 'text-xs text-emerald-300';
              ml.textContent = `Legacy ML (historical only): ${Math.round(item.ml_probability * 100)}%`;
              card.appendChild(ml);
            }
            if (isPast) {
              card.title = 'Select this hour in historical forecast comparison';
              card.addEventListener('click', async () => {
                await loadForecastHistory(item.timestamp);
                document.getElementById('forecastHistory')?.scrollIntoView({behavior:'smooth', block:'start'});
              });
            } else {
              card.title = 'Inspect this hour in the future forecast cards';
              card.addEventListener('click', () => {
                if (!state.savedDays) return;
                for (let i = 0; i < state.savedDays.length; i++) {
                  const hour = state.savedDays[i].hours.find(h => h.timestamp === item.timestamp);
                  if (hour) {
                    state.isLive = true;
                    state.daysData = state.savedDays;
                    state.selectedDayIdx = i;
                    state.selectedHourIdx = hour.idx;
                    renderSelectedDay();
                    document.getElementById('selectedDateLabel')?.scrollIntoView({behavior:'smooth', block:'center'});
                    return;
                  }
                }
              });
            }
            node.appendChild(card);
          }
        };
        draw(pastNode, payload.past, true);
        draw(futureNode, payload.future, false);
        status.textContent = `${payload.past.length} recorded past hours · ${payload.future.length} future hours from downloaded HRRR · sparse sampling, not continuous coverage`;
      } catch (err) {
        status.textContent = `Could not load forecast window: ${err.message}`;
      }
    }

    // The only routine refresh button: explicit, bounded network I/O, in order.
    let unifiedRefreshRunning = false;
    async function refreshEverything() {
      if (unifiedRefreshRunning) return;
      const buttons = ['refreshEverythingButton', 'refreshAllButton']
        .map(id => document.getElementById(id)).filter(Boolean);
      const status = document.getElementById('refreshEverythingStatus');
      const details = document.getElementById('refreshEverythingDetails');
      unifiedRefreshRunning = true;
      buttons.forEach(button => button.disabled = true);
      const selected = document.getElementById('historyTimeSelect')?.value;
      if (status) status.textContent = 'Starting refresh: future forecasts first…';
      try {
        const response = await fetch('/api/refresh/all', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({event_utc: selected || null})
        });
        const started = await response.json();
        if (!response.ok) throw new Error(started.detail || 'Could not start refresh');
        let finished = false;
        for (let i = 0; i < 2400; i++) {
          const poll = await fetch(`/api/refresh/all/status?job_id=${encodeURIComponent(started.id)}`);
          const job = await poll.json();
          if (!poll.ok) throw new Error(job.detail || 'Refresh status unavailable');
          if (status) status.textContent = job.message || 'Updating NOAA forecasts…';
          if (details) details.textContent = (job.results || []).map(step =>
            `${step.stage}: ${step.status === 'ok' ? 'complete' : step.message}`).join(' · ') ||
            'Downloading selected forecast data; existing predictions remain visible.';
          if (job.state === 'complete') {
            const failed = (job.results || []).filter(step => step.status === 'error');
            await fetchWeatherData(true);
            await loadForecastWindow();
            await loadForecastHistory(selected || null);
            if (status) status.textContent = failed.length
              ? `Refresh finished with ${failed.length} step error(s). Existing saved forecasts were preserved.`
              : 'Refresh complete · future forecasts, past comparisons, and airport observations updated.';
            finished = true;
            break;
          }
          await new Promise(resolve => setTimeout(resolve, 1500));
        }
        if (!finished && status) status.textContent = 'Refresh is still running on the server. Reload this page later to view saved results.';
      } catch (error) {
        if (status) status.textContent = `Refresh could not complete: ${error.message}`;
      } finally {
        unifiedRefreshRunning = false;
        buttons.forEach(button => button.disabled = false);
      }
    }

    async function refreshQuicklook() {
      await fetchWeatherData();
      await loadForecastWindow();
      await loadForecastHistory();
    }

    function convertForecast(hours) {
      const daysMap = new Map();
      for (const record of hours) {
        const date = record.local_time.split('T')[0];
        if (!daysMap.has(date)) daysMap.set(date, []);
        const dayHours = daysMap.get(date);
        const localHour = Number(record.local_time.slice(11, 13));
        dayHours.push({
          ...record, idx: dayHours.length, hour: localHour,
          timeStr: record.local_time.slice(11,16),
          probability: record.scenic_heuristic_score,
          lowSetupScore: record.heuristic_score,
          mlScore: record.ml_probability === null ? null : Math.round(record.ml_probability * 100),
          xgbScore: record.xgb_probability === null ? null : Math.round(record.xgb_probability * 100),
          cnnScore: record.cnn_probability === null ? null : Math.round(record.cnn_probability * 100),
          ceiling: null, temp750: null,
        });
      }
      const keys = [...daysMap.keys()].slice(0, 4);
      return keys.map((dateStr, idx) => {
        const dayHours = daysMap.get(dateStr);
        const morning = dayHours.filter(h => h.hour >= 4 && h.hour <= 10);
        const candidates = morning.length ? morning : dayHours;
        const best = candidates.reduce((a,b) => (a.probability ?? -1) >= (b.probability ?? -1) ? a : b);
        // Date generated at UTC noon to avoid changing calendar day across U.S. zones.
        const dateObj = new Date(`${dateStr}T12:00:00Z`);
        return {
          dateStr, dateObj,
          dayLabel: idx === 0 ? 'Today' : idx === 1 ? 'Tomorrow' : dateObj.toLocaleDateString('en-US', {weekday:'short',timeZone:'UTC'}),
          dateFormatted: dateObj.toLocaleDateString('en-US', {month:'numeric',day:'numeric',timeZone:'UTC'}),
          hours: dayHours, peakHour: best.idx, peakProb: best.probability,
        };
      });
    }

    /**
     * Render UI for selected day & peak/clicked hour
     */
    function renderSelectedDay() {
      if (!state.daysData || state.daysData.length === 0) return;

      const dayObj = state.daysData[state.selectedDayIdx] || state.daysData[0];
      
      // Update Day Label Tags
      document.getElementById('selectedDateLabel').textContent = `${dayObj.dayLabel} (${dayObj.dateFormatted})`;
      document.getElementById('chartDayLabel').textContent = `${dayObj.dayLabel} (${dayObj.dateFormatted})`;

      // Find peak hour if not explicitly selected
      const currentHourData = dayObj.hours[state.selectedHourIdx] || dayObj.hours[dayObj.peakHour] || dayObj.hours[0];
      state.selectedHourIdx = currentHourData.idx;

      // Update Peak Time Badge
      const formatTime = (h) => {
        const ampm = h >= 12 ? 'PM' : 'AM';
        const h12 = h % 12 === 0 ? 12 : h % 12;
        return `${h12}:00 ${ampm}`;
      };
      
      const peak = dayObj.hours[dayObj.peakHour];
      document.getElementById('peakTimeBadge').textContent = `Morning best: ${formatTime(peak.hour)}`;
      const tz = currentHourData.local_time ?
        new Intl.DateTimeFormat('en-US',{timeZone:'America/Denver', timeZoneName:'short'}).formatToParts(new Date(currentHourData.timestamp)).find(x=>x.type==='timeZoneName')?.value || 'MT' : 'MT';
      document.getElementById('currentHourBadge').textContent = `${formatTime(currentHourData.hour)} ${tz}`;

      // Render Gauge & Main Verdict Box
      renderGaugeAndVerdict(currentHourData);

      // Render SVG Elevation Cross Section Diagram
      renderSVGDiagram(currentHourData);

      // Render Short-range Outlook Strip
      render7DayStrip();

      // Render 24-Hour Timeline SVG Chart
      renderHourlyChart(dayObj);

      // Render Metric Breakdown Cards
      renderMetricCards(currentHourData);
      renderLandmarkForecasts(currentHourData);
      renderForecastComparison(currentHourData);

      // Render Hiking Recommendations Strategy
      renderHikingPlan(currentHourData);
      renderWeatherExplorer(currentHourData, dayObj);
      renderSolarForDay(dayObj);
      renderExtendedMetrics(currentHourData);
      renderFoothillsTransect(currentHourData);
    }

    /**
     * Render Probability Gauge Arc & Verdict Box
     */
    function renderGaugeAndVerdict(h) {
      const probPercent = document.getElementById('probPercent');
      const gaugeArc = document.getElementById('gaugeArc');
      const score = h.probability ?? 0;

      probPercent.textContent = state.isLive ? (h.probability == null ? '—' : `${score}/100`) : `${score}%`;

      // SVG Circle Gauge Arc calculation (r=50, circumference = 314.15)
      const circumference = 314.15;
      const strokeOffset = circumference - (score / 100) * circumference;
      gaugeArc.style.strokeDashoffset = strokeOffset;

      const badge = document.getElementById('probCategory');
      const verdictTitle = document.getElementById('verdictTitle');
      const verdictDesc = document.getElementById('verdictDesc');
      const verdictIcon = document.getElementById('verdictIcon');
      const verdictContainer = document.getElementById('verdictIconContainer');

      if (state.isLive) {
        gaugeArc.setAttribute('class', score >= 65 ? 'gauge-circle stroke-emerald-400' : score >= 35 ? 'gauge-circle stroke-cyan-400' : 'gauge-circle stroke-amber-400');
        badge.className = 'text-[10px] font-bold uppercase tracking-wide text-cyan-300 mt-1 px-2 py-1 bg-slate-900 rounded border border-slate-700';
        badge.textContent = 'HEURISTIC INDEX · NOT A PROBABILITY';
        verdictTitle.textContent = h.probability == null ? 'Scenic assessment unavailable' : (score >= 65 ? 'Potential above-the-clouds setup' : score >= 25 ? 'Mixed summit-clearing signals' : 'Poor above-the-clouds setup');
        verdictDesc.textContent = `${h.scenic_heuristic_reason || 'Scenic inputs unavailable.'} Low-cloud setup: ${h.lowSetupScore}/100. Scenic index: ${h.probability == null ? 'unavailable' : score + '/100'}. Neither is a probability or verified summit condition.`;
        verdictIcon.className = 'fa-solid fa-cloud-sun text-cyan-400';
        verdictContainer.className = 'p-2.5 rounded-xl bg-cyan-950 text-cyan-400 text-lg flex-shrink-0';
        return;
      }

      if (score >= 80) {
        gaugeArc.setAttribute('class', 'gauge-circle stroke-emerald-400');
        badge.textContent = "SYNTHETIC CLASSIC SCENARIO";
        badge.className = "text-xs font-bold uppercase tracking-wider text-emerald-400 mt-1 px-3 py-1 bg-emerald-950/90 rounded-full border border-emerald-700/60";

        verdictTitle.textContent = "Sea of Clouds Over Boulder Valley!";
        verdictDesc.textContent = `Boulder (5,400') is submerged in thick fog while 1st Flatiron (7,258') and Green Mt (8,133') sit in warm, brilliant sunshine above the deck!`;
        verdictIcon.className = "fa-solid fa-cloud-sun text-emerald-400";
        verdictContainer.className = "p-2.5 rounded-xl bg-emerald-950 text-emerald-400 text-lg flex-shrink-0";
      } else if (score >= 50) {
        gaugeArc.setAttribute('class', 'gauge-circle stroke-cyan-400');
        badge.textContent = "SYNTHETIC HIGH SCORE";
        badge.className = "text-xs font-bold uppercase tracking-wider text-cyan-400 mt-1 px-3 py-1 bg-cyan-950/90 rounded-full border border-cyan-700/60";

        verdictTitle.textContent = "Favorable Cloud Ceiling Setup";
        verdictDesc.textContent = `Cloud breakout layer estimated around ~${h.ceiling.toLocaleString()} ft. Summit of Green Mt (8,133') will be clear of fog.`;
        verdictIcon.className = "fa-solid fa-mountain text-cyan-400";
        verdictContainer.className = "p-2.5 rounded-xl bg-cyan-950 text-cyan-400 text-lg flex-shrink-0";
      } else if (score >= 25) {
        gaugeArc.setAttribute('class', 'gauge-circle stroke-amber-400');
        badge.textContent = "SYNTHETIC MARGINAL";
        badge.className = "text-xs font-bold uppercase tracking-wider text-amber-400 mt-1 px-3 py-1 bg-amber-950/90 rounded-full border border-amber-700/60";

        verdictTitle.textContent = "Marginal Cloud Ceiling";
        verdictDesc.textContent = "Cloud deck may be patchy or elevated. Higher peaks may drift in and out of fog.";
        verdictIcon.className = "fa-solid fa-smog text-amber-400";
        verdictContainer.className = "p-2.5 rounded-xl bg-amber-950 text-amber-400 text-lg flex-shrink-0";
      } else {
        gaugeArc.setAttribute('class', 'gauge-circle stroke-rose-400');
        badge.textContent = "SYNTHETIC CLEAR SKY";
        badge.className = "text-xs font-bold uppercase tracking-wider text-rose-400 mt-1 px-3 py-1 bg-rose-950/90 rounded-full border border-rose-700/60";

        const reason = h.windSpeed > 14 ? "Strong downslope Chinook winds blowing out valley moisture." : "Dry atmosphere column with crisp, clear views at all elevations.";
        verdictTitle.textContent = "Clear Atmosphere (No Cloud Layer)";
        verdictDesc.textContent = reason;
        verdictIcon.className = "fa-solid fa-sun text-rose-400";
        verdictContainer.className = "p-2.5 rounded-xl bg-rose-950 text-rose-400 text-lg flex-shrink-0";
      }
    }

    /**
     * Update Interactive SVG Mountain Cross-Section Diagram
     */
    function renderSVGDiagram(h) {
      const fogRect = document.getElementById('fogRect');
      const fogPuffs = document.getElementById('fogTopPuffs');
      const upperCloudPath = document.getElementById('upperCloudPath');
      const breakoutLineGroup = document.getElementById('breakoutLineGroup');
      const breakoutText = document.getElementById('breakoutText');
      const breakoutLine = document.getElementById('breakoutLine');
      const clearNotice = document.getElementById('clearSkyNotice');

      // SVG Altitude Mapping:
      // 8,133 ft (Green Mt) -> Y = 95
      // 7,258 ft (1st Flatiron) -> Y = 150
      // 5,400 ft (Boulder City) -> Y = 270
      // Base -> Y = 380

      const score = h.probability ?? 0;
      const ceiling = h.ceiling;

      if (state.isLive && ceiling === null) {
        fogRect.setAttribute('opacity','0');
        fogPuffs.setAttribute('opacity','0');
        upperCloudPath.setAttribute('opacity', ((h.midClouds + h.highClouds) / 200) * .8);
        breakoutLineGroup.style.display = 'none';
        clearNotice.style.display = 'block';
        clearNotice.querySelector('text').textContent = 'CLOUD TOP NOT VERIFIED';
        ['txtBadgeBoulder','txtBadgeFlatiron','txtBadgeGreenMt'].forEach(id=>{
          document.getElementById(id).textContent = 'UNVERIFIED';
        });
        return;
      }
      clearNotice.querySelector('text').textContent = 'ILLUSTRATIVE CLEAR SKY';

      // Calculate Fog SVG Y Position
      // Linear mapping from MSL altitude to SVG Y pixel:
      // Y = 270 - ((alt - 5400) / (8100 - 5400)) * (270 - 95)
      let fogY = 270 - ((ceiling - 5400) / 2700) * 175;
      let opacity = (h.lowClouds / 100) * 0.9;

      if (score < 20) {
        // Low probability -> Clear air mode
        opacity = 0.0;
        fogY = 350;
        clearNotice.style.display = 'block';
        breakoutLineGroup.style.display = 'none';
      } else {
        clearNotice.style.display = 'none';
        breakoutLineGroup.style.display = 'block';
      }

      // Update Fog Rect & Puffs
      fogRect.setAttribute('y', fogY);
      fogRect.setAttribute('height', 380 - fogY);
      fogRect.setAttribute('opacity', opacity);

      fogPuffs.setAttribute('d', `M 0,${fogY} Q 50,${fogY-15} 100,${fogY} T 200,${fogY} T 300,${fogY} T 400,${fogY} T 500,${fogY} T 600,${fogY} T 700,${fogY} T 800,${fogY} L 800,380 L 0,380 Z`);
      fogPuffs.setAttribute('opacity', opacity > 0 ? 0.65 : 0);

      // Upper Mid/High Cloud Layer
      const avgUpper = (h.midClouds + h.highClouds) / 2;
      upperCloudPath.setAttribute('opacity', (avgUpper / 100) * 0.85);

      // Breakout Line & Text
      if (score >= 20) {
        breakoutLine.setAttribute('y1', fogY);
        breakoutLine.setAttribute('y2', fogY);
        document.getElementById('breakoutLabelBg').setAttribute('y', fogY - 12);
        breakoutText.setAttribute('y', fogY + 2);
        breakoutText.textContent = `Estimated Cloud Top: ~${ceiling.toLocaleString()} ft MSL`;
      }

      // Dynamic Landmark Status Badges (In Fog vs Above Fog vs Clear Sky)
      updateLandmarkBadge('txtBadgeBoulder', 'badgeBoulder', ELEV_BOULDER, ceiling, score);
      updateLandmarkBadge('txtBadgeFlatiron', 'badgeFlatiron', ELEV_FLATIRON, ceiling, score);
      updateLandmarkBadge('txtBadgeGreenMt', 'badgeGreenMt', ELEV_GREEN_MT, ceiling, score);
    }

    /**
     * Helper to style landmark badges on SVG (In Fog / Above Clouds)
     */
    function updateLandmarkBadge(txtId, groupId, landmarkAlt, cloudCeiling, score) {
      const txtNode = document.getElementById(txtId);
      const groupNode = document.getElementById(groupId);
      if (!txtNode || !groupNode) return;

      const rectNode = groupNode.querySelector('rect');

      if (score < 20) {
        txtNode.textContent = "☀️ CLEAR SKY";
        txtNode.setAttribute('fill', '#fde047');
        rectNode.setAttribute('fill', '#451a03');
        rectNode.setAttribute('stroke', '#f59e0b');
      } else if (cloudCeiling >= landmarkAlt) {
        txtNode.textContent = "☁️ IN FOG";
        txtNode.setAttribute('fill', '#e2e8f0');
        rectNode.setAttribute('fill', '#1e293b');
        rectNode.setAttribute('stroke', '#64748b');
      } else {
        txtNode.textContent = "☀️ ABOVE CLOUDS";
        txtNode.setAttribute('fill', '#34d399');
        rectNode.setAttribute('fill', '#064e3b');
        rectNode.setAttribute('stroke', '#10b981');
      }
    }

    /**
     * Render Short-range Outlook Strip
     */
    function render7DayStrip() {
      const strip = document.getElementById('forecastStrip');
      strip.innerHTML = '';

      state.daysData.forEach((day, idx) => {
        const isSelected = idx === state.selectedDayIdx;
        const score = day.peakProb ?? 0;
        const hasScenic = day.peakProb != null;

        let scoreClass = "bg-rose-950/60 text-rose-400 border-rose-800/40";
        let iconClass = "fa-sun text-amber-400";
        if (score >= 75) {
          scoreClass = "bg-emerald-950/80 text-emerald-300 border-emerald-700/60";
          iconClass = "fa-cloud-sun text-emerald-400";
        } else if (score >= 45) {
          scoreClass = "bg-cyan-950/80 text-cyan-300 border-cyan-700/60";
          iconClass = "fa-smog text-cyan-400";
        }

        const borderClass = isSelected ? "border-cyan-400 bg-cyan-950/40 ring-1 ring-cyan-400/50 shadow-lg" : "border-slate-800 bg-slate-900/80 hover:border-slate-700";

        const cardHtml = `
          <div onclick="selectDay(${idx})" class="cursor-pointer border rounded-2xl p-3 flex flex-col justify-between items-center text-center transition ${borderClass}">
            <div>
              <div class="text-xs font-bold ${isSelected ? 'text-cyan-300' : 'text-slate-200'}">${day.dayLabel}</div>
              <div class="text-[10px] text-slate-400 font-mono">${day.dateFormatted}</div>
            </div>

            <div class="my-2.5 flex flex-col items-center">
              <i class="fa-solid ${iconClass} text-lg my-1"></i>
              <span class="text-xl font-black font-mono text-white">${state.isLive ? (hasScenic ? score + '/100' : '—') : score + '%'}</span>
            </div>

            <span class="text-[10px] font-bold px-2 py-0.5 rounded-full border ${scoreClass} w-full truncate">
              ${state.isLive ? (!hasScenic ? 'No scenic data' : score >= 65 ? 'Promising' : score >= 25 ? 'Mixed' : 'Poor scenic setup') : (score >= 75 ? 'Epic demo' : score >= 45 ? 'Moderate demo' : 'Unlikely demo')}
            </span>
          </div>
        `;

        strip.innerHTML += cardHtml;
      });
    }

    /** Plot the actual intended scenic index, or the distinct low-cloud score. */
    function renderHourlyChart(dayObj) {
      const svg = document.getElementById('hourlyChartSVG');
      const hours = dayObj.hours;
      const left = 52, top = 18, height = 172, width = 826;
      const barWidth = width / hours.length;
      let content = '';
      [0,25,50,75,100].forEach(v => {
        const y = top + height - v / 100 * height;
        content += `<line x1="${left}" y1="${y}" x2="890" y2="${y}" stroke="#334155" stroke-dasharray="3 4" />`;
        content += `<text x="45" y="${y+4}" font-size="10" fill="#94a3b8" text-anchor="end">${v}</text>`;
      });
      hours.forEach((h,idx) => {
        const val = !state.isLive ? h.probability : state.chartMode === 'scenic'
          ? h.scenic_heuristic_score : state.chartMode === 'low'
          ? h.heuristic_score : h.lowClouds;
        const available = val != null && Number.isFinite(val);
        const barHeight = available ? Math.max(0, Math.min(100, val)) / 100 * height : 0;
        const x = left + idx*barWidth;
        const y = top + height - barHeight;
        const selected = idx === state.selectedHourIdx;
        const tint = selected ? '#fbbf24' : state.chartMode === 'scenic' ? '#34d399' : state.chartMode === 'low' ? '#06b6d4' : '#94a3b8';
        content += `<rect onclick="selectHour(${idx})" x="${x+2}" y="${y}" width="${Math.max(3,barWidth-4)}" height="${Math.max(1,barHeight)}" rx="3" fill="${tint}" opacity="${selected?1:0.78}" class="chart-bar-hover"><title>${h.timeStr}: ${available ? Math.round(val) : 'N/A'}${state.chartMode === 'clouds' ? '%' : '/100 index'}</title></rect>`;
        if (idx % 3 === 0) content += `<text x="${x+barWidth/2}" y="225" font-size="10" text-anchor="middle" fill="#94a3b8">${h.timeStr}</text>`;
      });
      svg.innerHTML = content;
      const current = hours[state.selectedHourIdx] || hours[0];
      document.getElementById('chartSelectedHourInfo').textContent = state.isLive
        ? `${current.timeStr} · Scenic ${current.scenic_heuristic_score ?? '—'}/100 · Low-cloud ${current.heuristic_score}/100 · Low clouds ${Math.round(current.lowClouds)}%`
        : `${current.timeStr} · Synthetic demonstration`;
    }

    function setChartMode(mode) {
      state.chartMode = mode;
      ['scenic','low','clouds'].forEach((option) => {
        const node = document.getElementById('btnMode' + option.charAt(0).toUpperCase() + option.slice(1));
        if (!node) return;
        node.className = option === mode
          ? 'px-3 py-2 rounded-xl text-xs font-bold bg-cyan-950 text-cyan-300 border border-cyan-800/80'
          : 'px-3 py-2 rounded-xl text-xs font-bold text-slate-400 hover:text-white';
      });
      renderSelectedDay();
    }

    /**
     * User clicks a day in the 72-hour strip
     */
    function selectDay(dayIdx) {
      stopAtmospherePlay();
      state.selectedDayIdx = dayIdx;
      const dayObj = state.daysData[dayIdx];
      state.selectedHourIdx = dayObj ? dayObj.peakHour : 0;
      renderSelectedDay();
    }

    /**
     * User clicks an hour on the 24-hour chart
     */
    function selectHour(idx) {
      stopAtmospherePlay();
      state.selectedHourIdx = idx;
      renderSelectedDay();
    }

    /**
     * Render Metric Breakdown Cards
     */
    function renderMetricCards(h) {
      document.getElementById('metricLowClouds').textContent = `${h.lowClouds}%`;
      document.getElementById('barLowClouds').style.width = `${h.lowClouds}%`;

      const upperClear = state.isLive ? Math.round(h.scenic_upper_clear_factor ?? 0) : Math.max(0, Math.round(100 - (h.midClouds + h.highClouds) / 2));
      document.getElementById('metricClearSky').textContent = `${upperClear}%`;
      document.getElementById('barClearSky').style.width = `${upperClear}%`;

      const delta = h.tempDelta.toFixed(1);
      document.getElementById('metricTempDelta').textContent = `${delta > 0 ? '+' : ''}${delta}°C`;
      document.getElementById('valSurfTemp').textContent = `${h.surfTemp}°C`;
      document.getElementById('valHighTemp').textContent = Number.isFinite(h.tempDelta) && Number.isFinite(h.surfTemp) ? `${(h.surfTemp + h.tempDelta).toFixed(1)}°C` : 'Unavailable';

      document.getElementById('metricWindSpeed').textContent = `${h.windSpeed} mph`;
      document.getElementById('metricWindDir').textContent = getWindDirAbbr(h.windDir);
      document.getElementById('windArrow').style.transform = `rotate(${h.windDir}deg)`;

      const windQuality = (h.windDir >= 40 && h.windDir <= 140) ? Math.min(100, (15 - h.windSpeed) * 8) : 25;
      document.getElementById('barWind').style.width = `${Math.max(10, windQuality)}%`;
    }

    /** Altitude is an explicit target, but do not fabricate summit-clear odds. */
    function renderLandmarkForecasts(h) {
      const panel = document.getElementById('landmarkForecasts');
      const caption = document.getElementById('cloudBaseSummary');
      if (!panel || !caption) return;
      if (!state.isLive) {
        panel.textContent = 'Synthetic scenario; no validated mountain probabilities.';
        caption.textContent = '';
        return;
      }
      const sites = h.landmarks || [];
      panel.replaceChildren();
      sites.forEach(site => {
        const block = document.createElement('div');
        block.className = 'bg-slate-900 border border-slate-700 rounded-xl p-3';
        const name = document.createElement('div');
        name.className = 'text-sm font-bold text-slate-200';
        name.textContent = `${site.name} · ${site.elevation_ft.toLocaleString()} ft`;
        const score = document.createElement('div');
        score.className = 'text-lg font-bold text-cyan-300 mt-2';
        score.textContent = site.scenic_heuristic_score == null ? (site.name === 'Boulder' ? 'Valley reference' : 'Scenic index unavailable') : `Scenic heuristic ${site.scenic_heuristic_score}/100`;
        const mlBadge = document.createElement('p');
        mlBadge.className = 'text-xs text-slate-400';
        mlBadge.textContent = site.scenic_probability == null ? 'Summit outcome: not verified' : `Experimental scenic estimate: ${Math.round(site.scenic_probability * 100)}%`; 
        const relation = site.relative_to_modeled_cloud_top;
        const modelHint = relation === 'above_modeled_cloud_top' ? 'HRRR cloud-top field below this elevation.' : relation === 'below_modeled_cloud_top' ? 'HRRR cloud-top field above this elevation.' : relation === 'near_modeled_cloud_top' ? 'Near HRRR modeled cloud top (±450 ft).' : 'HRRR cloud-top height unavailable.';
        const explanation = document.createElement('p');
        explanation.className = 'text-xs text-slate-400 mt-1';
        explanation.textContent = site.scenic_probability === null
          ? `No verified scenic probability. ${modelHint} Cloud-top field may include higher clouds and need not describe Boulder\'s low cloud deck.`
          : `Legacy archived scenic probability. ${modelHint}`;
        if (site.scenic_heuristic_reason) explanation.textContent = site.scenic_heuristic_reason + ' RH at summit: ' + (site.forecast_rh_at_summit_pct ?? 'N/A') + '%. Unverified HRRR proxy, not a probability.';
        block.append(name, score, mlBadge, explanation);
        panel.appendChild(block);
      });
      const b = h.estimated_low_cloud_base_ft_msl;
      const range = h.cloud_base_80pct_residual_interval_ft_msl;
      caption.textContent = b === null ? 'HRRR cloud-base and humidity diagnostics are forecast fields, not a verified low-cloud top.'
        : `Estimated low-cloud BASE near KBDU: ${b.toLocaleString()} ft MSL` +
          (range ? ` (validation 80% absolute-residual band: ${range[0].toLocaleString()}–${range[1].toLocaleString()} ft).` : '.') +
          ' This is NOT the top of the cloud layer or a guarantee of a clear peak.';
    }

    /** Physically specific mountain target; profile humidity is only a proxy. */
    function renderScenicEvidence(h) {
      const node = document.getElementById('scenicDetails');
      const scoreNode = document.getElementById('scenicScore');
      const flatiron = document.getElementById('scenicFlatiron');
      if (!state.isLive) {
        scoreNode.textContent = '—';
        flatiron.textContent = 'Synthetic demo; no real HRRR scenic assessment.';
        node.replaceChildren();
        return;
      }
      scoreNode.textContent = h.scenic_heuristic_score == null ? 'N/A' : `${h.scenic_heuristic_score}/100`;
      flatiron.textContent = `First Flatiron (7,258 ft): ${h.scenic_flatiron_score == null ? 'N/A' : h.scenic_flatiron_score + '/100'} · Low-cloud-only index: ${h.heuristic_score}/100`;
      node.replaceChildren();
      const header = document.createElement('p');
      header.className = 'text-sm font-semibold text-slate-100';
      header.textContent = h.scenic_heuristic_reason || 'Missing summit evaluation.';
      node.appendChild(header);
      const data = h.scenic_indicators || {};
      const readings = [
        ['Low cloud coverage near Boulder', data.low_cloud_cover_pct, '%'],
        ['Middle cloud cover (unwanted)', data.mid_cloud_cover_pct, '%'],
        ['High cloud cover (unwanted)', data.high_cloud_cover_pct, '%'],
        ['HRRR forecast cloud base', data.forecast_cloud_base_ft_msl, 'ft MSL'],
        ['Preferred low-deck top: at or below', data.max_desired_low_deck_top_ft_msl, 'ft MSL'],
        ['RH near 7,400 ft', data.green_rh_at_7400ft_pct, '%'],
        ['RH near Green Mt summit (8,133 ft)', data.green_rh_at_summit_pct, '%'],
        ['RH above Green Mt', data.green_rh_above_summit_pct, '%'],
        ['RH-profile drying transition (not cloud top)', h.scenic_profile_drying_transition_ft_msl, 'ft MSL'],
        ['HRRR whole-column cloud top (may be high clouds)', data.forecast_overall_cloud_top_ft_msl, 'ft MSL'],
      ];
      const list = document.createElement('dl');
      list.className = 'grid grid-cols-1 md:grid-cols-2 gap-2 text-xs';
      readings.forEach(([name, value, unit]) => {
        const box = document.createElement('div');
        box.className = 'border border-slate-700 rounded-lg px-3 py-2';
        const term = document.createElement('dt');
        term.className = 'text-slate-400';
        term.textContent = name;
        const number = document.createElement('dd');
        number.className = 'font-mono font-semibold text-slate-100';
        number.textContent = value == null ? 'Not resolved' : `${Number(value).toLocaleString('en-US', {maximumFractionDigits:1})} ${unit}`;
        box.append(term, number);
        list.appendChild(box);
      });
      node.appendChild(list);
      const method = document.createElement('p');
      method.className = 'text-xs text-sky-200';
      method.textContent = `Smooth upper-cloud penalty: middle-cloud factor ${h.scenic_mid_sky_factor ?? '—'}/100 × high-cloud factor ${h.scenic_high_sky_factor ?? '—'}/100 → combined ${h.scenic_upper_clear_factor ?? '—'}/100. These factors are hand-designed, not observed clear-sky percentages.`;
      node.appendChild(method);
      const spatial = h.scenic_spatial_uncertainty;
      const near = document.createElement('p');
      near.className = spatial?.classification === 'high' ? 'text-xs text-amber-200' : 'text-xs text-slate-400';
      near.textContent = spatial?.available
        ? `Nearby HRRR grid cloud disagreement (${spatial.count} nearby points): mid spread ${spatial.cloud_spread_pct.mid_cloud_pct} pp, high spread ${spatial.cloud_spread_pct.high_cloud_pct} pp (${spatial.classification}). This is not measured summit sky.`
        : 'Nearby-grid cloud diagnostics not available in this cached HRRR forecast; newly downloaded forecast records include them.';
      node.appendChild(near);
      const text = document.createElement('p');
      text.className = 'text-xs text-amber-200';
      text.textContent = h.scenic_disclaimer || 'Not a validated mountain visibility probability.';
      node.appendChild(text);
    }

    /** Display the transparent HRRR indices continuously. */
    function renderForecastComparison(h) {
      const componentNode = document.getElementById('heuristicComponents');
      const top = document.getElementById('modeledCloudTop');
      if (!state.isLive) {
        componentNode.textContent = 'Synthetic preset. No real forecast ingredients.';
        renderScenicEvidence(h);
        top.textContent = 'No real forecast cloud height.';
        return;
      }
      renderHeuristicEvidence(componentNode, h);
      renderScenicEvidence(h);
      const cloudTop = h.forecast_cloud_top_ft_msl;
      const cloudBase = h.forecast_cloud_base_ft_msl;
      top.textContent = `HRRR modeled cloud base: ${cloudBase == null ? 'not reported' : cloudBase.toLocaleString() + ' ft MSL'} · cloud top: ${cloudTop == null ? 'not reported' : cloudTop.toLocaleString() + ' ft MSL'}. Model forecast fields; not independently verified cloud-deck bounds.`;
    }

    /**
     * Render Hiking & Landmark Recommendations Strategy
     */
    function renderHikingPlan(h) {
      const alarm = document.getElementById('recAlarmTime');
      const thTitle = document.getElementById('recTrailheadTitle');
      const thDesc = document.getElementById('recTrailheadDesc');
      const boTitle = document.getElementById('recBreakoutTitle');
      const boDesc = document.getElementById('recBreakoutDesc');
      const gearTitle = document.getElementById('recGearTitle');
      const gearDesc = document.getElementById('recGearDesc');

      const score = h.probability ?? 0;
      const ceiling = h.ceiling;

      if (state.isLive && ceiling === null) {
        alarm.textContent = 'Use local sunrise / trail conditions';
        thTitle.textContent = 'Check webcams and local observations';
        thDesc.textContent = 'A model forecast cannot guarantee you will climb above fog. Check current cloud bases, visibility, wind and trail conditions.';
        boTitle.textContent = h.estimated_low_cloud_base_ft_msl !== null ? `Reported-cloud-base estimate ~${Math.round(h.estimated_low_cloud_base_ft_msl).toLocaleString()} ft MSL` : 'Cloud-base and cloud-top unavailable';
        boDesc.textContent = 'HRRR cloud base and RH profile are diagnostics, not observed cloud top. Summit clearance remains unverified.';
        gearTitle.textContent = 'Prepare for uncertain conditions';
        gearDesc.textContent = 'Carry a headlamp, warm and windproof layers, and navigation. Avoid committing to a hike based on this experimental score alone.';
        return;
      }

      if (score >= 70) {
        alarm.textContent = "5:15 AM MDT";
        thTitle.textContent = "1st Flatiron Ridge or Green Mt";
        thDesc.textContent = "Start at Chautauqua Ranger Cottage and hike up Gregory Canyon to break out above the 6,700' fog deck early.";

        boTitle.textContent = `Cloud Ceiling: ~${ceiling.toLocaleString()} ft MSL`;
        boDesc.textContent = "Boulder (5,400') submerged in dense fog; 1st Flatiron (7,258') and Green Mt (8,133') are in full warm sunshine!";

        gearTitle.textContent = "High-Contrast Photography Pack";
        gearDesc.textContent = "Headlamp required for lower fog trail. Pack sunglasses and ND filter for golden hour over the sea of clouds.";
      } else if (score >= 40) {
        alarm.textContent = "5:45 AM MDT";
        thTitle.textContent = "Green Mountain Summit Target";
        thDesc.textContent = "Higher cloud ceiling today (~7,500'). Target Green Mountain Summit (8,133') for guaranteed clear mountain views.";

        boTitle.textContent = `Cloud Ceiling: ~${ceiling.toLocaleString()} ft MSL`;
        boDesc.textContent = "Boulder and 1st Flatiron enveloped in fog; Green Mt summit breaks out above the cloud line.";

        gearTitle.textContent = "Damp Trail & Moisture Layering";
        gearDesc.textContent = "Pack waterproof shell for damp lower trail and headlamp for early morning start.";
      } else {
        alarm.textContent = "7:30 AM / Regular Hike";
        thTitle.textContent = "Standard Day Hike (Clear Air)";
        thDesc.textContent = "Inversion deck unlikely today. Crisp mountain views expected at all elevations.";

        boTitle.textContent = "No Cloud Inversion Ceiling";
        boDesc.textContent = "Valley floor, 1st Flatiron, and Green Mt all share clear atmospheric visibility.";

        gearTitle.textContent = "Standard Daypack Essentials";
        gearDesc.textContent = "Standard daylight hiking gear. Check wind advisory if strong westerly downslope winds are present.";
      }
    }

    /** All frames are actual sampled forecast hours; never interpolate new forecast data. */
    function atmosphereFrames() {
      return (state.daysData || []).flatMap((day, dayIndex) =>
        day.hours.map((hour, hourIndex) => ({dayIndex, hourIndex, hour})));
    }

    function stopAtmospherePlay() {
      if (explorerPlayback !== null) {
        window.clearInterval(explorerPlayback);
        explorerPlayback = null;
      }
      const button = document.getElementById('explorerPlay');
      if (button) button.innerHTML = '<i class="fa-solid fa-play mr-1"></i> Play';
    }

    function selectAtmosphereFrame(position, fromPlayback = false) {
      const frames = atmosphereFrames();
      const index = Math.max(0, Math.min(frames.length - 1, Math.round(position)));
      if (!frames.length) return;
      if (!fromPlayback) stopAtmospherePlay();
      const selected = frames[index];
      state.selectedDayIdx = selected.dayIndex;
      state.selectedHourIdx = selected.hourIndex;
      renderSelectedDay();
    }

    function stepAtmosphere(direction, fromPlayback = false) {
      const frames = atmosphereFrames();
      if (!frames.length) return false;
      const selected = frames.findIndex(frame => frame.dayIndex === state.selectedDayIdx &&
        frame.hourIndex === state.selectedHourIdx);
      const next = selected + direction;
      if (next < 0 || next >= frames.length) {
        if (fromPlayback) stopAtmospherePlay();
        return false;
      }
      selectAtmosphereFrame(next, fromPlayback);
      return true;
    }

    function toggleAtmospherePlay() {
      if (explorerPlayback !== null) return stopAtmospherePlay();
      if (atmosphereFrames().length < 2) return;
      explorerPlayback = window.setInterval(() => stepAtmosphere(1, true), 1200);
      document.getElementById('explorerPlay').innerHTML = '<i class="fa-solid fa-pause mr-1"></i> Pause';
    }

    function boulderTime(input, options = {}) {
      if (!input) return '—';
      const date = new Date(input);
      if (Number.isNaN(date.getTime())) return '—';
      return date.toLocaleString('en-US', {
        timeZone: 'America/Denver', ...options
      });
    }

    function finiteNumber(value) {
      return value == null || value === '' || !Number.isFinite(Number(value)) ? null : Number(value);
    }
    function readingValue(value, unit = '', digits = 0) {
      const n = finiteNumber(value);
      if (n === null) return 'Not available';
      return `${n.toLocaleString('en-US', {maximumFractionDigits: digits, minimumFractionDigits: digits})}${unit}`;
    }

    function renderWeatherExplorer(hour, dayObj) {
      const frames = atmosphereFrames();
      const cursor = frames.findIndex(frame => frame.dayIndex === state.selectedDayIdx &&
        frame.hourIndex === state.selectedHourIdx);
      const slider = document.getElementById('explorerSlider');
      slider.max = String(Math.max(0, frames.length - 1));
      slider.value = String(Math.max(0, cursor));
      slider.disabled = frames.length < 2;
      document.getElementById('explorerPrevious').disabled = cursor <= 0;
      document.getElementById('explorerNext').disabled = cursor >= frames.length - 1;
      if (frames.length) {
        const first = frames[0].hour, last = frames[frames.length - 1].hour;
        const fmt = h => h.timestamp ? boulderTime(h.timestamp, {month:'short', day:'numeric', hour:'numeric', minute:'2-digit'}) : h.timeStr;
        const sampled = frames[Math.round((frames.length - 1)/2)].hour;
        document.getElementById('explorerTicks').replaceChildren(...[first,sampled,last].map(h => {
          const span = document.createElement('span');span.textContent = fmt(h);return span;
        }));
      }
      const displayTime = hour.timestamp
        ? boulderTime(hour.timestamp, {weekday:'short', month:'short', day:'numeric', hour:'numeric', minute:'2-digit', timeZoneName:'short'})
        : `${dayObj.dateFormatted} ${hour.timeStr}`;
      document.getElementById('explorerTime').textContent = displayTime;
      document.getElementById('explorerRun').textContent = state.isLive
        ? `Forecast run ${boulderTime(hour.run_utc, {month:'short',day:'numeric',hour:'numeric',timeZoneName:'short'})} · F${hour.lead_hours} · ${frames.length} actual sampled forecast hours`
        : 'SYNTHETIC DEMO · weather data, cloud layers and scores are fabricated';
      const low = Math.max(0, Math.min(100, finiteNumber(hour.lowClouds) ?? 0));
      const mid = Math.max(0, Math.min(100, finiteNumber(hour.midClouds) ?? 0));
      const high = Math.max(0, Math.min(100, finiteNumber(hour.highClouds) ?? 0));
      document.getElementById('explorerHighCloud').setAttribute('opacity', String(high / 100 * .8));
      document.getElementById('explorerMidCloud').setAttribute('opacity', String(mid / 100 * .75));
      const fogGroup = document.getElementById('explorerLowCloud');
      const transition = state.isLive ? finiteNumber(hour.scenic_profile_drying_transition_ft_msl) : finiteNumber(hour.ceiling);
      const base = state.isLive ? finiteNumber(hour.forecast_cloud_base_ft_msl) : ELEV_BOULDER;
      const meaningfulTransition = transition !== null && transition > 5250 && transition < 9300 &&
        (base === null || transition >= base);
      // Diagram coordinates are an elevation illustration, not a resolved HRRR vertical cross section.
      const altitudeY = feet => Math.max(56, Math.min(350, 319 - (feet - 5400) * 195 / 2733));
      const topY = meaningfulTransition ? altitudeY(transition) : 209;
      fogGroup.setAttribute('opacity', String(low / 100 * .85));
      const fogFill = document.getElementById('explorerFogFill');
      fogFill.setAttribute('y', String(topY));
      fogFill.setAttribute('height', String(Math.max(0, 405 - topY)));
      fogFill.setAttribute('fill', meaningfulTransition ? 'url(#explorerLowFog)' : 'url(#explorerUncertainFog)');
      const edge = document.getElementById('explorerFogEdge');
      edge.setAttribute('d', `M 0 ${topY} Q 80 ${topY-13} 160 ${topY} T320 ${topY} T480 ${topY} T640 ${topY} T800 ${topY} T960 ${topY}`);
      edge.setAttribute('opacity', meaningfulTransition ? '.75' : '.10');
      const line = document.getElementById('explorerDryingGroup');
      line.setAttribute('opacity', meaningfulTransition && low >= 30 ? '1' : '0');
      document.getElementById('explorerDryingLine').setAttribute('y1', String(topY));
      document.getElementById('explorerDryingLine').setAttribute('y2', String(topY));
      document.getElementById('explorerDryingText').textContent = meaningfulTransition
        ? `RH drying near ${Math.round(transition).toLocaleString()} ft · NOT cloud top` : 'Low-cloud top not resolved';
      document.getElementById('explorerSceneCondition').textContent = low >= 70
        ? 'HRRR: extensive low cloud' : low >= 25 ? 'HRRR: patchy low cloud' : 'HRRR: little low cloud';
      document.getElementById('explorerSceneCaption').textContent = meaningfulTransition
        ? `HRRR low cloud ${Math.round(low)}% · RH drying proxy ${Math.round(transition).toLocaleString()} ft · peak clearance UNVERIFIED`
        : `HRRR low cloud ${Math.round(low)}% · cloud-layer TOP NOT RESOLVED · schematic only`;
      document.getElementById('explorerScenic').textContent = state.isLive
        ? readingValue(hour.scenic_heuristic_score,'/100') : `${Math.round(hour.probability)}/100 DEMO`;
      document.getElementById('explorerLow').textContent = state.isLive
        ? readingValue(hour.lowSetupScore,'/100') : 'DEMO';
      document.getElementById('explorerUpper').textContent = `${Math.round(mid)}% / ${Math.round(high)}%`;
      document.getElementById('explorerTop').textContent = meaningfulTransition
        ? `${Math.round(transition).toLocaleString()} ft RH proxy` : 'Not resolved';
      const spatial = hour.scenic_spatial_uncertainty;
      document.getElementById('explorerNotice').textContent = !state.isLive
        ? 'SYNTHETIC DEMONSTRATION. Nothing shown in this landscape is a weather forecast.'
        : `Low-cloud opacity and upper cloud icons reflect HRRR model cloud fractions near KBDU. ` +
          (meaningfulTransition ? 'The dashed level is a coarse RH drying transition, NOT a verified cloud-top height. ' : 'No reliable low-deck top is available; the fog gradient is illustrative only. ') +
          (spatial?.available ? `Nearby-grid upper-cloud variability: ${spatial.classification}. ` : 'Nearby-grid variability not available in this run. ') +
          'Terrain drawing is schematic; mountain-specific weather is not directly observed.';
      const solar = solarTimesCache.get(dayObj.dateStr);
      const stamp = hour.timestamp ? new Date(hour.timestamp) : null;
      const dawn = solar?.civil_dawn && new Date(solar.civil_dawn);
      const dusk = solar?.civil_dusk && new Date(solar.civil_dusk);
      const day = solar?.sunrise && new Date(solar.sunrise);
      const end = solar?.sunset && new Date(solar.sunset);
      const isNight = Boolean(stamp && dawn && dusk && (stamp < dawn || stamp > dusk));
      const twilight = Boolean(stamp && day && end && (stamp < day || stamp > end));
      document.getElementById('explorerNightOverlay').setAttribute('opacity', isNight ? '.82' : twilight ? '.46' : '.04');
      document.getElementById('explorerStars').setAttribute('opacity', isNight ? '.92' : '0');
      document.getElementById('explorerSun').setAttribute('opacity', twilight ? '0' : '.9');
    }

    async function renderSolarForDay(dayObj) {
      const dateStr = dayObj.dateStr;
      if (!solarTimesCache.has(dateStr)) {
        if (solarLoading.has(dateStr)) return;
        solarLoading.add(dateStr);
        try {
          const response = await fetch(`/api/solar?date_local=${encodeURIComponent(dateStr)}`);
          if (!response.ok) throw new Error('Solar timetable unavailable');
          solarTimesCache.set(dateStr, await response.json());
        } catch (error) {
          console.warn('Solar calculation error:', error);
          solarTimesCache.set(dateStr, {date:dateStr,error:String(error)});
        } finally {
          solarLoading.delete(dateStr);
        }
        const selected = state.daysData?.[state.selectedDayIdx];
        if (selected && selected.dateStr !== dateStr) return;
        if (selected) renderWeatherExplorer(selected.hours[state.selectedHourIdx], selected);
      }
      const solar = solarTimesCache.get(dateStr);
      document.getElementById('solarDate').textContent = `${dateStr} · Boulder local time`;
      const cards = document.getElementById('solarCards');
      cards.replaceChildren();
      for (const [title, key, icon, color] of [
        ['Civil dawn','civil_dawn','fa-cloud-moon','text-sky-300'],
        ['Sunrise','sunrise','fa-sun','text-amber-300'],
        ['Morning golden ends','morning_golden_end','fa-camera','text-yellow-200'],
        ['Evening golden begins','evening_golden_start','fa-camera','text-yellow-200'],
        ['Sunset','sunset','fa-sun-plant-wilt','text-orange-300'],
        ['Civil dusk','civil_dusk','fa-moon','text-sky-300']
      ]) {
        const card = document.createElement('div');
        card.className = 'rounded-xl border border-slate-800 bg-slate-900/85 p-3';
        const label = document.createElement('p');
        label.className = 'text-[11px] text-slate-400';
        label.textContent = title;
        const value = document.createElement('p');
        value.className = `text-lg font-extrabold font-mono mt-2 ${color}`;
        value.textContent = solar?.[key] ? boulderTime(solar[key],{hour:'numeric',minute:'2-digit',timeZoneName:'short'}) : '—';
        card.append(label, value);
        cards.appendChild(card);
      }
      const minutes = solar?.daylight_minutes;
      if (solar?.sunrise && state.isLive) {
        const startAdvice = document.getElementById('recAlarmTime');
        if (startAdvice && startAdvice.textContent === 'Use local sunrise / trail conditions') {
          startAdvice.textContent = `Sunrise ${boulderTime(solar.sunrise,{hour:'numeric',minute:'2-digit'})} · allow ascent time`;
        }
      }
      document.getElementById('solarDaylight').textContent = minutes == null
        ? 'Daylight duration unavailable'
        : `Daylight ${Math.floor(minutes/60)}h ${minutes%60}m · Apparent horizon sunrise/sunset (not terrain-corrected)`;
      if (solar?.sunrise && solar?.sunset) {
        const sunrise = new Date(solar.sunrise), sunset = new Date(solar.sunset);
        const midnight = new Date(sunrise);
        // Visual percentage within local civil day using the local ISO clock portion.
        const minuteOfDay = iso => Number(iso.slice(11,13))*60 + Number(iso.slice(14,16));
        const a = Math.max(0,Math.min(100,minuteOfDay(solar.sunrise)/14.4));
        const b = Math.max(0,Math.min(100,(minuteOfDay(solar.sunset)-minuteOfDay(solar.sunrise))/14.4));
        document.getElementById('daylightBar').innerHTML = `<div class="bg-slate-700" style="width:${a}%"></div><div class="bg-gradient-to-r from-amber-500 via-sky-400 to-amber-500" style="width:${b}%"></div><div class="bg-slate-700 flex-1"></div>`;
      }
    }

    const ROUTE_TARGETS = [
      {id:'kbdu',name:'Boulder airport',latitude:40.0394,longitude:-105.2250},
      {id:'east_boulder',name:'East Boulder',latitude:40.0260,longitude:-105.2470},
      {id:'downtown',name:'Central Boulder',latitude:40.0150,longitude:-105.2705},
      {id:'chautauqua',name:'Chautauqua',latitude:39.9978,longitude:-105.2814},
      {id:'flatiron',name:'First Flatiron',latitude:39.990472,longitude:-105.294667},
      {id:'green',name:'Green Mountain',latitude:39.9794304,longitude:-105.3016578},
    ];
    const svgNS = 'http://www.w3.org/2000/svg';
    function createSvgElement(tag, attrs = {}, value = '') {
      const element = document.createElementNS(svgNS, tag);
      Object.entries(attrs).forEach(([key, val]) => element.setAttribute(key, String(val)));
      if (value) element.textContent = value;
      return element;
    }
    function renderFoothillsTransect(h) {
      const data = state.isLive ? h?.foothills_transect : null;
      const points = Array.isArray(data?.points) ? data.points : ROUTE_TARGETS.map(target => ({...target}));
      const map = document.getElementById('transectMap');
      const matrix = document.getElementById('transectHeatmap');
      const details = document.getElementById('transectSelectedDetails');
      if (!map || !matrix || !details) return;
      const available = Boolean(data && Array.isArray(data.points) && data.points.length);
      const metricLabels = {
        low_cloud_pct:'Low-cloud cover', mid_cloud_pct:'Middle-cloud cover',
        high_cloud_pct:'High-cloud cover', surface_rh_pct:'2 m relative humidity',
        rh_at_8133ft_pct:'RH at 8,133 ft MSL'
      };
      const percent = value => finiteNumber(value) === null ? '—' : `${Math.round(Number(value))}%`;
      const positions = points.map(p => ({...p,
        x: 45 + (p.longitude + 105.312) / (.100) * 545,
        y: 23 + (40.047 - p.latitude) / (.077) * 262
      }));
      // Blue encodes a large forecast cloud or RH fraction. Gray is unknown.
      const shade = value => {
        const n = finiteNumber(value);
        if (n === null) return '#64748b';
        return `hsl(${Math.round(40 + 160 * Math.max(0, Math.min(100, n)) / 100)} 72% 53%)`;
      };
      map.replaceChildren();
      map.appendChild(createSvgElement('rect',{x:0,y:0,width:640,height:320,rx:12,fill:'#081529'}));
      for (let k=0;k<5;k++) {
        const y=24+k*63;
        map.append(createSvgElement('line',{x1:34,x2:617,y1:y,y2:y,stroke:'#334155','stroke-dasharray':'3 7'}));
      }
      for (let k=0;k<7;k++) {
        const x=34+k*94;
        map.append(createSvgElement('line',{x1:x,x2:x,y1:20,y2:292,stroke:'#334155','stroke-dasharray':'3 7'}));
      }
      const polyline = positions.map(p=>`${p.x},${p.y}`).join(' ');
      map.append(createSvgElement('polyline',{points:polyline,fill:'none',stroke:'#64748b','stroke-width':5,'stroke-linecap':'round',opacity:.7}));
      map.append(createSvgElement('polyline',{points:polyline,fill:'none',stroke:'#a5f3fc','stroke-width':2,'stroke-dasharray':'8 6',opacity:.8}));
      map.append(createSvgElement('text',{x:580,y:21,'font-size':12,fill:'#94a3b8','text-anchor':'end'},'N ↑'));
      map.append(createSvgElement('text',{x:28,y:307,'font-size':11,fill:'#94a3b8'},'W ← Mountains'));
      map.append(createSvgElement('text',{x:615,y:307,'font-size':11,fill:'#94a3b8','text-anchor':'end'},'Plains → E'));
      positions.forEach((p,i)=>{
        const selected = p.id === transectSelected;
        const group = createSvgElement('g',{role:'button',tabindex:0,'aria-label':`${p.name}: ${metricLabels[transectMetric]} ${percent(p[transectMetric])}`});
        const circle = createSvgElement('circle',{cx:p.x,cy:p.y,r:selected?11:8,fill:shade(p[transectMetric]),stroke:selected?'#ffffff':'#b5c7d6','stroke-width':selected?3:1.5});
        group.append(circle);
        const anchorX = i <= 2 ? p.x-14 : p.x+14;
        const labelY = i===4 ? p.y+18 : i===5 ? p.y+17 : i===3 ? p.y-22 : p.y-12;
        const label = createSvgElement('text',{x:anchorX,y:labelY,'text-anchor':i<=2?'end':'start',fill:'#eff6ff',stroke:'#081529','stroke-width':3,'paint-order':'stroke','font-size':11,'font-weight':600},p.name);
        group.append(label);
        const onSelect = ()=>{transectSelected=p.id;renderFoothillsTransect(h);};
        group.addEventListener('click',onSelect);
        group.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();onSelect();}});
        group.style.cursor='pointer';
        map.append(group);
      });
      // Interactive geographic basemap when Leaflet is available. The SVG
      // remains a fast, self-contained fallback if a CDN/tile service is down.
      const leafletCanvas=document.getElementById('transectLeaflet');
      const coordinatePlot=document.getElementById('transectMap');
      const mapSource=document.getElementById('transectMapSource');
      if(window.L && leafletCanvas){
        try {
          leafletCanvas.classList.remove('hidden');
          coordinatePlot.classList.add('hidden');
          mapSource.textContent='OpenStreetMap contributors · markers colored by HRRR fields, NOT observations';
          if(!leafletTransectMap){
            leafletTransectMap=L.map(leafletCanvas,{scrollWheelZoom:false}).setView([40.009,-105.273],12);
            L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{
              attribution:'© OpenStreetMap contributors',maxZoom:18
            }).addTo(leafletTransectMap);
            leafletTransectLayers=L.layerGroup().addTo(leafletTransectMap);
            const line=ROUTE_TARGETS.map(p=>[p.latitude,p.longitude]);
            leafletTransectMap.fitBounds(L.latLngBounds(line).pad(.18));
          }
          leafletTransectLayers.clearLayers();
          L.polyline(positions.map(p=>[p.latitude,p.longitude]),{
            color:'#67e8f9',weight:3,dashArray:'7 6',opacity:.85
          }).addTo(leafletTransectLayers);
          for(const point of positions){
            const marker=L.circleMarker([point.latitude,point.longitude],{
              radius:point.id===transectSelected?12:9,
              color:'#ffffff',weight:point.id===transectSelected?3:1.5,
              fillColor:shade(point[transectMetric]),fillOpacity:.94
            });
            marker.bindTooltip(`${point.name} · ${metricLabels[transectMetric]} ${percent(point[transectMetric])}`);
            marker.on('click',()=>{transectSelected=point.id;renderFoothillsTransect(h);});
            marker.addTo(leafletTransectLayers);
          }
          window.setTimeout(()=>leafletTransectMap?.invalidateSize(),50);
        }catch(error){
          console.warn('Map tiles unavailable: falling back to coordinate plot',error);
          leafletCanvas.classList.add('hidden');coordinatePlot.classList.remove('hidden');
        }
      }else if(leafletCanvas){
        leafletCanvas.classList.add('hidden');coordinatePlot.classList.remove('hidden');
        mapSource.textContent='Offline coordinate diagram · sample positions plotted to scale';
      }
      const selected = points.find(p=>p.id===transectSelected) || points[0];
      const selectedIndex = points.findIndex(p=>p.id===selected.id);
      const tiles = [
        ['Selected location',selected.name],
        [metricLabels[transectMetric],percent(selected[transectMetric])],
        ['Low / mid / high',`${percent(selected.low_cloud_pct)} / ${percent(selected.mid_cloud_pct)} / ${percent(selected.high_cloud_pct)}`],
        ['Surface RH',percent(selected.surface_rh_pct)],
        ['RH at summit height',percent(selected.rh_at_summit_pct)],
        ['HRRR grid terrain',finiteNumber(selected.grid_terrain_ft_msl) === null?'—':`${Math.round(selected.grid_terrain_ft_msl).toLocaleString()} ft`],
      ];
      details.replaceChildren();
      for (const [label,value] of tiles) {
        const card=document.createElement('div');card.className='rounded-xl bg-slate-900/85 border border-slate-800 p-3';
        const title=document.createElement('p');title.className='text-[11px] text-slate-400';title.textContent=label;
        const reading=document.createElement('p');reading.className='text-sm font-semibold text-slate-100 mt-1';reading.textContent=value;
        card.append(title,reading);details.append(card);
      }
      // Relative humidity heatmap, rendered only within each point's
      // above-ground pressure-level sample envelope. No extrapolation.
      const levels = [10500,9500,8500,8133,7600,7258,7000,6500,6000,5500];
      const cols = Array.isArray(data?.points) ? data.points : [];
      matrix.replaceChildren();
      if (!available) {
        const message=document.createElement('p');message.className='text-sm text-amber-200 py-8';
        message.textContent=state.isLive
          ? 'This saved HRRR hour predates the spatial sampler. Choose “Load spatial data for selected hour” to fetch only the missing fields.'
          : 'Spatial HRRR values are unavailable in synthetic demonstration mode.';
        matrix.append(message);
      } else {
        const table=document.createElement('table');table.className='w-full border-separate border-spacing-[2px] text-[10px] text-slate-200';
        const head=document.createElement('thead');const tr=document.createElement('tr');
        for (const name of ['ft MSL',...cols.map(p=>p.name.split(' ')[0])]) {
          const th=document.createElement('th');th.className='px-1 py-1.5 text-center text-slate-300';th.textContent=name;tr.append(th);
        }
        head.append(tr);table.append(head);
        const body=document.createElement('tbody');
        const rhAt=(point,at)=>{
          const layers=point.humidity_by_height||[];
          for(let i=1;i<layers.length;i++){
            const a=layers[i-1],b=layers[i];
            if(at>=a.height_ft_msl&&at<=b.height_ft_msl && b.height_ft_msl>a.height_ft_msl){
              return a.rh_pct + (b.rh_pct-a.rh_pct)*(at-a.height_ft_msl)/(b.height_ft_msl-a.height_ft_msl);
            }
          }
          return null;
        };
        for(const height of levels){
          const tr=document.createElement('tr');
          const th=document.createElement('th');th.className='text-right pr-2 py-1 whitespace-nowrap text-slate-400 font-mono';th.textContent=height.toLocaleString();tr.append(th);
          cols.forEach(point=>{
            const val=rhAt(point,height);
            const cell=document.createElement('td');cell.textContent=percent(val);
            cell.title=`${point.name}, ${height.toLocaleString()} ft: ${val==null?'not resolved':val.toFixed(1)+'% RH'}`;
            cell.style.backgroundColor=shade(val);
            cell.style.color=val==null?'#e2e8f0':'#07111f';
            cell.style.opacity=point.id===selected.id?'1':'.86';
            cell.className='text-center font-mono font-semibold rounded px-1 py-1';
            tr.append(cell);
          });
          body.append(tr);
        }
        table.append(body);matrix.append(table);
      }
      document.getElementById('transectCells').textContent = available
        ? `${data.unique_model_cells ?? '?'} distinct HRRR cells / ${points.length} locations`
        : 'Grid cells: not downloaded';
      document.getElementById('transectMapTime').textContent = h.timestamp
        ? boulderTime(h.timestamp,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})
        : 'No live HRRR spatial grid';
      document.getElementById('transectProvenance').textContent = available
        ? `NOAA HRRR ${h.run_utc} · F${h.lead_hours}. ${data.unique_model_cells??'Unknown number of'} distinct nearest-grid cells for ${points.length} markers. ` +
          'Grid terrain is smoothed and differs from true summit height. The pressure-RH profile cannot directly resolve a shallow fog top.'
        : 'Older cached hours have only Boulder grid-cell measurements. Spatial locations are shown for context, but no spatial values have been inferred.';
      const button=document.getElementById('transectFetchButton');
      button.disabled=!state.isLive || !h.timestamp || available || transectRefreshPolling;
      button.textContent=available?'Spatial samples loaded for this hour':'Load spatial data for selected hour';
      button.classList.toggle('opacity-50',available);
      // Keep a link to a real geographic map; the SVG is only coordinate plot.
      let link=document.getElementById('transectLocationLink');
      if(!link){link=document.createElement('a');link.id='transectLocationLink';link.className='text-cyan-300 hover:text-cyan-100 underline text-xs';
        document.getElementById('transectProvenance').after(link);}
      link.href=`https://www.openstreetmap.org/?mlat=${selected.latitude}&mlon=${selected.longitude}#map=14/${selected.latitude}/${selected.longitude}`;
      link.target='_blank';link.rel='noopener noreferrer';link.textContent=`View ${selected.name} on OpenStreetMap`;
      if(available && selected.grid_id){link.title=`Nearest HRRR grid cell ${selected.grid_id}; different markers can share this cell`;}
      // Official NOAA inventories describe the raw GRIB2 fields; the values
      // in the map are extracted from those fields at nearest grid cells.
      let sources=document.getElementById('transectNoaaSources');
      if(!sources){
        sources=document.createElement('div');sources.id='transectNoaaSources';
        sources.className='flex flex-wrap gap-3 text-xs text-cyan-300';
        link.after(sources);
      }
      sources.replaceChildren();
      if(h.run_utc && finiteNumber(h.lead_hours)!==null){
        const run=new Date(h.run_utc);
        if(!Number.isNaN(run.getTime())){
          const date=run.toISOString().slice(0,10).replaceAll('-','');
          const hh=String(run.getUTCHours()).padStart(2,'0');
          const ff=String(Math.round(h.lead_hours)).padStart(2,'0');
          for(const [kind,label] of [['sfc','NOAA surface GRIB inventory'],['prs','NOAA pressure GRIB inventory']]){
            const a=document.createElement('a');a.target='_blank';a.rel='noopener noreferrer';
            a.href=`https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.${date}/conus/hrrr.t${hh}z.wrf${kind}f${ff}.grib2.idx`;
            a.textContent=label;a.className='underline hover:text-white';sources.append(a);
          }
        }
      }
    }
    function changeTransectMetric(metric) {
      if(!['low_cloud_pct','mid_cloud_pct','high_cloud_pct','surface_rh_pct','rh_at_8133ft_pct'].includes(metric)) return;
      transectMetric=metric;
      const day=state.daysData?.[state.selectedDayIdx];
      if(day)renderFoothillsTransect(day.hours[state.selectedHourIdx]||day.hours[0]);
    }
    async function fetchSelectedTransect() {
      if(transectRefreshPolling || !state.isLive) return;
      const day=state.daysData?.[state.selectedDayIdx];
      const row=day?.hours[state.selectedHourIdx];
      if(!row?.timestamp)return;
      const chosenTime=row.timestamp;
      const status=document.getElementById('transectFetchStatus');
      transectRefreshPolling=true;
      const button=document.getElementById('transectFetchButton');button.disabled=true;
      try {
        status.textContent='Starting selected-hour HRRR spatial download…';
        const start=await fetch('/api/transect/refresh',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({timestamp:chosenTime})
        });
        const started=await start.json();
        if(!start.ok)throw Error(started.detail||'Could not start transect download');
        let result=started;
        for(let attempt=0;attempt<180 && result.state==='running';attempt++){
          await new Promise(resolve=>setTimeout(resolve,1200));
          const response=await fetch(`/api/transect/refresh/status?job_id=${encodeURIComponent(started.id)}`);
          if(!response.ok)throw Error('Spatial job status is unavailable');
          result=await response.json();
          status.textContent=result.message||'Reading HRRR fields…';
        }
        if(result.state==='running')throw Error('Spatial download is still processing; reload to check later.');
        if(result.state==='error')throw Error(result.message||'Spatial download failed');
        // Reload the actual local forecast API, then restore the selected hour.
        await fetchWeatherData(false);
        for(let i=0;i<state.daysData.length;i++){
          const j=state.daysData[i].hours.findIndex(h=>h.timestamp===chosenTime);
          if(j>=0){state.selectedDayIdx=i;state.selectedHourIdx=j;renderSelectedDay();break;}
        }
        status.textContent='Spatial data loaded for this forecast hour.';
      } catch(error) {
        status.textContent=`Spatial retrieval: ${error.message}`;
      } finally {
        transectRefreshPolling=false;
        const day=state.daysData?.[state.selectedDayIdx];
        if(day)renderFoothillsTransect(day.hours[state.selectedHourIdx]||day.hours[0]);
      }
    }

    function renderExtendedMetrics(h) {
      const panel = document.getElementById('forecastMetricsExtended');
      panel.replaceChildren();
      const card = (label, value, note) => {
        const box = document.createElement('div');
        box.className='rounded-xl border border-slate-800 bg-slate-900/75 p-3 space-y-1';
        const small = document.createElement('p');small.className='text-[11px] text-slate-400';small.textContent=label;
        const strong = document.createElement('p');strong.className='font-mono font-semibold text-white text-base';strong.textContent=value;
        const hint = document.createElement('p');hint.className='text-[10px] text-slate-500 leading-snug';hint.textContent=note;
        box.append(small,strong,hint);panel.appendChild(box);
      };
      const scenic = state.isLive;
      const details = h.scenic_indicators || {};
      const spatial = h.scenic_spatial_uncertainty;
      card('Green Mt scenic', scenic ? readingValue(h.scenic_heuristic_score, '/100') : 'DEMO', 'Heuristic rank; not probability');
      card('First Flatiron scenic', scenic ? readingValue(h.scenic_flatiron_score, '/100') : 'DEMO', 'Target 7,258 ft MSL');
      card('Boulder low-cloud setup', scenic ? readingValue(h.lowSetupScore,'/100') : 'DEMO', 'Separate original heuristic');
      card('Low / mid / high clouds', `${readingValue(h.lowClouds,'%')} / ${readingValue(h.midClouds,'%')} / ${readingValue(h.highClouds,'%')}`, 'Model cloud-layer coverage');
      card('Air temperature · 2 m', readingValue(h.surfTemp,' °C',1), 'Forecast, not a measurement');
      card('Dew point · 2 m', readingValue(h.dewPoint,' °C',1), 'Moisture condensation threshold');
      card('Relative humidity · 2 m', readingValue(h.rh,'%',1), 'Model surface humidity');
      const depression = finiteNumber(h.surfTemp) !== null && finiteNumber(h.dewPoint) !== null
        ? h.surfTemp - h.dewPoint : null;
      card('Dew-point depression', readingValue(depression,' °C',1), 'Near zero means near saturation');
      card('300 m temperature change', readingValue(h.tempDelta,' °C',1), 'Positive = warming with altitude');
      card('10 m wind', `${readingValue(h.windSpeed,' mph',1)} ${finiteNumber(h.windDir) === null ? '' : getWindDirAbbr(h.windDir)}`, 'Modeled local surface wind');
      card('Visibility', readingValue(finiteNumber(h.forecast_visibility_m) === null ? null : h.forecast_visibility_m/1609.344,' mi',1), 'HRRR prediction; not observed');
      card('Boundary-layer height', readingValue(h.forecast_boundary_layer_height_m,' m',0), 'Model mixing-layer diagnostic');
      card('Cloud-base estimate', readingValue(h.forecast_cloud_base_ft_msl,' ft MSL'), 'Generic modeled base, not summit-specific');
      card('RH drying transition', readingValue(h.scenic_profile_drying_transition_ft_msl,' ft MSL'), 'NOT a verified low-cloud top');
      card('RH at Green Mt', readingValue(details.green_rh_at_summit_pct,'% ',1), 'Coarse HRRR vertical profile');
      card('RH below Green Mt', readingValue(details.green_rh_at_7400ft_pct,'%',1), 'Profile at ~7,400 ft MSL');
      card('Whole-column cloud top', readingValue(h.forecast_cloud_top_ft_msl,' ft MSL'), 'May refer to unrelated high clouds');
      card('Nearby cloud disagreement', spatial?.available ? `${spatial.classification} · ${spatial.count} points` : 'Not available',
        spatial?.available ? `Mid spread ${spatial.cloud_spread_pct?.mid_cloud_pct ?? '—'} pp; high spread ${spatial.cloud_spread_pct?.high_cloud_pct ?? '—'} pp` : 'Requires new HRRR download');
      document.getElementById('forecastMetricsTime').textContent = h.timestamp
        ? boulderTime(h.timestamp,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'})
        : `${h.timeStr} · demo`;
      const source = h.forecast_provenance || h.source_provenance || h.heuristic_provenance;
      document.getElementById('forecastEvidenceSource').textContent = state.isLive
        ? `NOAA HRRR run ${h.run_utc} · forecast F${h.lead_hours} · nearest model grid to KBDU. ` +
          'Cloud cover is not a direct summit observation; astronomy is calculated independently.'
        : 'SYNTHETIC DEMONSTRATION · not real atmospheric measurements.';
    }

    /**
     * Generate Synthetic 24-hour day for testing Presets
     */
    function generateSyntheticDay(name, targetCeiling, targetProb, surfT, t750, lowC, wDir) {
      const hours = [];
      for (let h = 0; h < 24; h++) {
        const isMorning = (h >= 5 && h <= 9);
        const prob = isMorning ? targetProb : Math.max(10, targetProb - Math.abs(h - 7) * 9);
        const ceiling = targetProb < 20 ? 5400 : targetCeiling;

        hours.push({
          hour: h,
          idx: h,
          timeStr: `${h.toString().padStart(2, '0')}:00`,
          lowClouds: isMorning ? lowC : 30,
          midClouds: 10,
          highClouds: 5,
          surfTemp: surfT,
          dewPoint: surfT - 1.0,
          rh: 90,
          temp750: t750,
          tempDelta: t750 - surfT,
          windSpeed: 5,
          windDir: wDir,
          probability: prob,
          ceiling: ceiling
        });
      }

      const dateObj = new Date();
      return [{
        dateStr: dateObj.toISOString().split('T')[0],
        dateObj: dateObj,
        dayLabel: 'Preset Scenario',
        dateFormatted: name,
        hours: hours,
        peakHour: 7,
        peakProb: targetProb
      }];
    }

    /**
     * Load Atmospheric Preset Scenario
     */
    function loadPreset(key) {
      stopAtmospherePlay();
      setActivePresetBtn(key);
      if (key === 'live') {
        if (state.savedDays?.length) {
          state.isLive = true;
          state.daysData = state.savedDays;
          state.selectedDayIdx = Math.min(1, state.daysData.length-1);
          state.selectedHourIdx = state.daysData[state.selectedDayIdx].peakHour;
          renderSelectedDay();
        } else fetchWeatherData();
        return;
      }
      const presetData = PRESETS[key];
      if (presetData) {
        state.isLive = false;
        state.daysData = presetData;
        state.selectedDayIdx = 0;
        state.selectedHourIdx = 7;
        document.getElementById('modelCaveat').textContent = 'DEMONSTRATION SCENARIO — all values and cloud layers are synthetic.';
        document.getElementById('apiStatusText').textContent = 'Synthetic demo scenario';
        renderSelectedDay();
      }
    }

    function setActivePresetBtn(activeKey) {
      document.querySelectorAll('.preset-btn').forEach(btn => {
        btn.className = "preset-btn px-3 py-1.5 rounded-xl font-medium border border-slate-700 bg-slate-900 text-slate-300 hover:border-slate-500 transition";
      });
      const activeBtn = document.getElementById(`btn-${activeKey}`);
      if (activeBtn) {
        activeBtn.className = "preset-btn px-3 py-1.5 rounded-xl font-medium border border-cyan-500 bg-cyan-950/80 text-cyan-300 shadow-sm transition";
      }
    }

    function getWindDirAbbr(deg) {
      const dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
      return dirs[Math.floor((deg / 22.5) + 0.5) % 16];
    }
