/**
     * Atmospheric Model & Coordinates Configuration
     * Open-Meteo API endpoint for Boulder, CO (40.0150, -105.2705)
     */
    const BOULDER_LAT = 40.0150;
    const BOULDER_LON = -105.2705;

    // Landmark Altitudes in ft MSL
    const ELEV_BOULDER = 5400;
    const ELEV_FLATIRON = 7200;
    const ELEV_GREEN_MT = 8100;

    // State object
    let state = {
      isLive: true,
      rawHourly: null,
      daysData: [],           // 7 days of 24h metrics
      selectedDayIdx: 1,      // Default 1 = Tomorrow
      selectedHourIdx: 6,     // Default to peak hour of selected day
      chartMode: 'probability' // 'probability' or 'elevation'
    };

    /**
     * Presets Data Structure for Instant Testing
     */
    const PRESETS = {
      epic: generateSyntheticDay("Classic Inversion (7,200' & 8,100' Above Fog)", 6700, 92, 2.0, 7.5, 95, 80),
      high: generateSyntheticDay("High Fog Deck (Only 8,100' Peak Above)", 7600, 84, 1.0, 4.0, 96, 60),
      socked: generateSyntheticDay("Deep Fog Deck (All 3 Socked In)", 8400, 76, 0.5, -2.0, 98, 40),
      clear: generateSyntheticDay("Bluebird / Downslope (No Inversion)", 5400, 12, 14.0, 3.0, 30, 270)
    };

    /**
     * Window Load Initializer
     */
    window.onload = function() {
      fetchWeatherData();
    };

    /**
     * Fetch Live Forecast Data from Open-Meteo API
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
        document.getElementById('apiStatusText').textContent = payload.model.verified_observations
          ? 'Observed-label model (experimental)' : 'Proxy-trained model — unverified';
        document.getElementById('statusBadge').classList.remove('hidden');
        document.getElementById('modelCaveat').textContent = payload.model.warning;
        setActivePresetBtn('live');
        renderSelectedDay();
      } catch (error) {
        console.error('Forecast unavailable:', error);
        document.getElementById('statusBadge').classList.remove('hidden');
        document.getElementById('apiStatusText').textContent = 'Forecast unavailable';
        document.getElementById('modelCaveat').textContent = String(error.message);
        document.getElementById('verdictTitle').textContent = 'Models not available';
        document.getElementById('verdictDesc').textContent = String(error.message);
        document.getElementById('probPercent').textContent = '--%';
        // Never replace a failed live forecast with a seemingly real demo.
        state.isLive = true;
        state.daysData = [];
        document.getElementById('forecastStrip').textContent = 'No live forecast available. Check the model training steps in README.';
        document.getElementById('hourlyChartSVG').innerHTML = '';
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
          probability: Math.round(record.probability * 100),
          xgbScore: Math.round(record.xgb_probability * 100),
          cnnScore: Math.round(record.cnn_probability * 100),
          ceiling: null, temp750: null,
        });
      }
      const keys = [...daysMap.keys()].slice(0, 7);
      return keys.map((dateStr, idx) => {
        const dayHours = daysMap.get(dateStr);
        const morning = dayHours.filter(h => h.hour >= 4 && h.hour <= 10);
        const candidates = morning.length ? morning : dayHours;
        const best = candidates.reduce((a,b) => a.probability >= b.probability ? a : b);
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

      // Render 7-Day Outlook Strip
      render7DayStrip();

      // Render 24-Hour Timeline SVG Chart
      renderHourlyChart(dayObj);

      // Render Metric Breakdown Cards
      renderMetricCards(currentHourData);

      // Render Hiking Recommendations Strategy
      renderHikingPlan(currentHourData);
    }

    /**
     * Render Probability Gauge Arc & Verdict Box
     */
    function renderGaugeAndVerdict(h) {
      const probPercent = document.getElementById('probPercent');
      const gaugeArc = document.getElementById('gaugeArc');
      const score = h.probability;

      probPercent.textContent = `${score}%`;

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
        const label = state.modelInfo?.verified_observations ? 'OBSERVATION-TRAINED ESTIMATE' : 'UNVERIFIED PROXY SCORE';
        gaugeArc.setAttribute('class', score >= 65 ? 'gauge-circle stroke-emerald-400' : score >= 35 ? 'gauge-circle stroke-cyan-400' : 'gauge-circle stroke-amber-400');
        badge.className = 'text-[10px] font-bold uppercase tracking-wide text-amber-400 mt-1 px-2 py-1 bg-slate-900 rounded border border-amber-900';
        badge.textContent = label;
        verdictTitle.textContent = `XGBoost ${h.xgbScore}% · CNN ${h.cnnScore}%`;
        verdictDesc.textContent = 'Ensemble estimates a low-fog, clearer-above setup. This is not a verified likelihood of a thermal inversion or a measured cloud ceiling. Check local observations before heading out.';
        verdictIcon.className = 'fa-solid fa-chart-line text-cyan-400';
        verdictContainer.className = 'p-2.5 rounded-xl bg-cyan-950 text-cyan-400 text-lg flex-shrink-0';
        return;
      }

      if (score >= 80) {
        gaugeArc.setAttribute('class', 'gauge-circle stroke-emerald-400');
        badge.textContent = "SYNTHETIC CLASSIC SCENARIO";
        badge.className = "text-xs font-bold uppercase tracking-wider text-emerald-400 mt-1 px-3 py-1 bg-emerald-950/90 rounded-full border border-emerald-700/60";

        verdictTitle.textContent = "Sea of Clouds Over Boulder Valley!";
        verdictDesc.textContent = `Boulder (5,400') is submerged in thick fog while 1st Flatiron (7,200') and Green Mt (8,100') sit in warm, brilliant sunshine above the deck!`;
        verdictIcon.className = "fa-solid fa-cloud-sun text-emerald-400";
        verdictContainer.className = "p-2.5 rounded-xl bg-emerald-950 text-emerald-400 text-lg flex-shrink-0";
      } else if (score >= 50) {
        gaugeArc.setAttribute('class', 'gauge-circle stroke-cyan-400');
        badge.textContent = "SYNTHETIC HIGH SCORE";
        badge.className = "text-xs font-bold uppercase tracking-wider text-cyan-400 mt-1 px-3 py-1 bg-cyan-950/90 rounded-full border border-cyan-700/60";

        verdictTitle.textContent = "Favorable Cloud Ceiling Setup";
        verdictDesc.textContent = `Cloud breakout layer estimated around ~${h.ceiling.toLocaleString()} ft. Summit of Green Mt (8,100') will be clear of fog.`;
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
      // 8,100 ft (Green Mt) -> Y = 95
      // 7,200 ft (1st Flatiron) -> Y = 150
      // 5,400 ft (Boulder City) -> Y = 270
      // Base -> Y = 380

      const score = h.probability;
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
     * Render 7-Day Outlook Strip
     */
    function render7DayStrip() {
      const strip = document.getElementById('forecastStrip');
      strip.innerHTML = '';

      state.daysData.forEach((day, idx) => {
        const isSelected = idx === state.selectedDayIdx;
        const score = day.peakProb;

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
              <span class="text-xl font-black font-mono text-white">${score}%</span>
            </div>

            <span class="text-[10px] font-bold px-2 py-0.5 rounded-full border ${scoreClass} w-full truncate">
              ${score >= 75 ? 'Epic' : score >= 45 ? 'Moderate' : 'Unlikely'}
            </span>
          </div>
        `;

        strip.innerHTML += cardHtml;
      });
    }

    /**
     * Render 24-Hour Timeline SVG Chart (Probability OR Elevation Mode)
     */
    function renderHourlyChart(dayObj) {
      const svg = document.getElementById('hourlyChartSVG');
      const hours = dayObj.hours;
      const showProb = state.chartMode === 'probability';
      const left = 52, top = 18, height = 172, width = 826;
      const barWidth = width / hours.length;
      let content = '';
      [0,25,50,75,100].forEach(v => {
        const y = top + height - v / 100 * height;
        content += `<line x1="${left}" y1="${y}" x2="890" y2="${y}" stroke="#334155" stroke-dasharray="3 4" />`;
        content += `<text x="45" y="${y+4}" font-size="10" fill="#94a3b8" text-anchor="end">${v}%</text>`;
      });
      hours.forEach((h,idx) => {
        const val = showProb ? h.probability : h.lowClouds;
        const barHeight = Math.max(0,Math.min(100,val)) / 100 * height;
        const x = left + idx*barWidth;
        const y = top + height - barHeight;
        const selected = idx === state.selectedHourIdx;
        content += `<rect onclick="selectHour(${idx})" x="${x+2}" y="${y}" width="${Math.max(3,barWidth-4)}" height="${barHeight}" rx="3" fill="${selected ? '#fbbf24' : showProb ? '#06b6d4' : '#94a3b8'}" opacity="${selected?1:0.78}" class="chart-bar-hover"><title>${h.timeStr}: ${Math.round(val)}%</title></rect>`;
        if (idx % 3 === 0) content += `<text x="${x+barWidth/2}" y="225" font-size="10" text-anchor="middle" fill="#94a3b8">${h.timeStr}</text>`;
      });
      svg.innerHTML = content;
      const current = hours[state.selectedHourIdx] || hours[0];
      document.getElementById('chartSelectedHourInfo').textContent =
        `${current.timeStr} · Ensemble ${current.probability}% · Low clouds ${Math.round(current.lowClouds)}%`;
    }

    /**
     * Set Chart View Mode (Probability vs Elevation)
     */
    function setChartMode(mode) {
      state.chartMode = mode;
      const btnProb = document.getElementById('btnModeProb');
      const btnElev = document.getElementById('btnModeElev');

      if (mode === 'probability') {
        btnProb.className = "px-4 py-2 rounded-xl text-xs font-bold transition flex items-center space-x-2 bg-cyan-950 text-cyan-300 border border-cyan-800/80 shadow";
        btnElev.className = "px-4 py-2 rounded-xl text-xs font-bold transition flex items-center space-x-2 text-slate-400 hover:text-white";
      } else {
        btnElev.className = "px-4 py-2 rounded-xl text-xs font-bold transition flex items-center space-x-2 bg-amber-950 text-amber-300 border border-amber-800/80 shadow";
        btnProb.className = "px-4 py-2 rounded-xl text-xs font-bold transition flex items-center space-x-2 text-slate-400 hover:text-white";
      }

      renderSelectedDay();
    }

    /**
     * User clicks a day in the 7-day strip
     */
    function selectDay(dayIdx) {
      state.selectedDayIdx = dayIdx;
      const dayObj = state.daysData[dayIdx];
      state.selectedHourIdx = dayObj ? dayObj.peakHour : 0;
      renderSelectedDay();
    }

    /**
     * User clicks an hour on the 24-hour chart
     */
    function selectHour(idx) {
      state.selectedHourIdx = idx;
      renderSelectedDay();
    }

    /**
     * Render Metric Breakdown Cards
     */
    function renderMetricCards(h) {
      document.getElementById('metricLowClouds').textContent = `${h.lowClouds}%`;
      document.getElementById('barLowClouds').style.width = `${h.lowClouds}%`;

      const upperClear = Math.max(0, Math.round(100 - (h.midClouds + h.highClouds)/2));
      document.getElementById('metricClearSky').textContent = `${upperClear}%`;
      document.getElementById('barClearSky').style.width = `${upperClear}%`;

      const delta = h.tempDelta.toFixed(1);
      document.getElementById('metricTempDelta').textContent = `${delta > 0 ? '+' : ''}${delta}°C`;
      document.getElementById('valSurfTemp').textContent = `${h.surfTemp}°C`;
      document.getElementById('valHighTemp').textContent = h.temp750 === null ? 'Unavailable' : `${h.temp750}°C`;

      document.getElementById('metricWindSpeed').textContent = `${h.windSpeed} mph`;
      document.getElementById('metricWindDir').textContent = getWindDirAbbr(h.windDir);
      document.getElementById('windArrow').style.transform = `rotate(${h.windDir}deg)`;

      const windQuality = (h.windDir >= 40 && h.windDir <= 140) ? Math.min(100, (15 - h.windSpeed) * 8) : 25;
      document.getElementById('barWind').style.width = `${Math.max(10, windQuality)}%`;
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

      const score = h.probability;
      const ceiling = h.ceiling;

      if (state.isLive && ceiling === null) {
        alarm.textContent = 'Use local sunrise / trail conditions';
        thTitle.textContent = 'Check webcams and local observations';
        thDesc.textContent = 'A model forecast cannot guarantee you will climb above fog. Check current cloud bases, visibility, wind and trail conditions.';
        boTitle.textContent = 'Cloud-top elevation unavailable';
        boDesc.textContent = 'This version predicts a proxy event score; it does not determine cloud-top height or summit visibility.';
        gearTitle.textContent = 'Prepare for uncertain conditions';
        gearDesc.textContent = 'Carry a headlamp, warm and windproof layers, and navigation. Avoid committing to a hike based on this experimental score alone.';
        return;
      }

      if (score >= 70) {
        alarm.textContent = "5:15 AM MDT";
        thTitle.textContent = "1st Flatiron Ridge or Green Mt";
        thDesc.textContent = "Start at Chautauqua Ranger Cottage and hike up Gregory Canyon to break out above the 6,700' fog deck early.";

        boTitle.textContent = `Cloud Ceiling: ~${ceiling.toLocaleString()} ft MSL`;
        boDesc.textContent = "Boulder (5,400') submerged in dense fog; 1st Flatiron (7,200') and Green Mt (8,100') are in full warm sunshine!";

        gearTitle.textContent = "High-Contrast Photography Pack";
        gearDesc.textContent = "Headlamp required for lower fog trail. Pack sunglasses and ND filter for golden hour over the sea of clouds.";
      } else if (score >= 40) {
        alarm.textContent = "5:45 AM MDT";
        thTitle.textContent = "Green Mountain Summit Target";
        thDesc.textContent = "Higher cloud ceiling today (~7,500'). Target Green Mountain Summit (8,100') for guaranteed clear mountain views.";

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
