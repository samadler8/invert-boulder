/* Boulder Inversion Outlook v6. All values come from local NOAA HRRR data,
 * independent airport METAR records, or astronomical calculations.
 * No synthetic demo modes, no fabricated cloud top, no ML inference.
 * Slider visits actual sampled forecast hours, without interpolation.
 */
'use strict';
const TZ = 'America/Denver';
const $ = id => document.getElementById(id);
const state = {future:[],past:[],index:0,playing:null,historyEvent:null,historyTimes:[],
  transectMetric:'low_cloud_pct', selectedLocation:'downtown', loading:false,solarDate:null,nws:null};
function escapeHTML(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function num(v){if(v===null||v===undefined||v===''||!Number.isFinite(Number(v)))return null;return Number(v);}
function fmt(v,unit='',digits=0){const n=num(v);return n===null?'—':n.toLocaleString('en-US',{maximumFractionDigits:digits,minimumFractionDigits:digits})+unit;}
function fmtDate(iso,options={}){if(!iso)return '—';const dt=new Date(iso);return Number.isNaN(+dt)?'—':new Intl.DateTimeFormat('en-US',{timeZone:TZ,...options}).format(dt);}
function timeLabel(iso){return fmtDate(iso,{weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'});}
function shortTime(iso){return fmtDate(iso,{hour:'numeric',minute:'2-digit'});}
function localDay(iso){let d=new Date(iso);if(Number.isNaN(+d))return null;let fields=Object.fromEntries(new Intl.DateTimeFormat('en-US',{timeZone:TZ,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(d).filter(p=>p.type!=='literal').map(p=>[p.type,p.value]));return `${fields.year}-${fields.month}-${fields.day}`;}
const safeLink=(url,text)=> /^https:\/\//.test(url||'')?`<a target="_blank" rel="noopener noreferrer" href="${escapeHTML(url)}">${escapeHTML(text)} ↗</a>`:'';
async function getJSON(url,options){const r=await fetch(url,{cache:'no-store',...options});let j;try{j=await r.json();}catch{throw Error(`HTTP ${r.status}`);}if(!r.ok)throw Error(j.detail||`HTTP ${r.status}`);return j;}
function notice(message,kind=''){const el=$('systemNotice');el.className='notice '+kind;el.textContent=message;}
function setText(id,value){const el=$(id);if(el)el.textContent=value;}
function bestForecast(){const all=state.future.filter(f=>num(f.opportunity_score)!==null);const mornings=all.filter(f=>{let h=Number(new Intl.DateTimeFormat('en-US',{timeZone:TZ,hour:'2-digit',hour12:false}).format(new Date(f.timestamp)));return h>=5&&h<=10;});return (mornings.length?mornings:all).slice().sort((a,b)=>b.opportunity_score-a.opportunity_score||new Date(a.timestamp)-new Date(b.timestamp))[0]||null;}
async function loadAll({keepSelection=true}={}){
  const original=keepSelection&&state.future[state.index]?.timestamp;
  try{const [windowData,nearby,storage,nws]=await Promise.all([
    getJSON('/api/window'),getJSON('/api/observations/nearby').catch(()=>({stations:[]})),
    getJSON('/api/storage').catch(()=>null),getJSON('/api/nws').catch(()=>({hours:[]}))]);
    state.nws=nws;
    state.future=(windowData.future||[]).sort((a,b)=>a.timestamp.localeCompare(b.timestamp));state.past=windowData.past||[];
    let next=state.future.findIndex(x=>x.timestamp===original);
    if(next<0){let best=bestForecast();next=best?state.future.findIndex(x=>x.timestamp===best.timestamp):0;}
    state.index=Math.max(0,next);
    $('explorerSlider').max=Math.max(0,state.future.length-1);$('explorerSlider').disabled=!state.future.length;
    if(state.future.length){notice(`${state.future.length} real HRRR forecast hours loaded. ${windowData.past.length} past hours in history. No synthetic weather.`, 'success');selectAtmosphereFrame(state.index);}
    else{notice(windowData.future_error||'No saved future HRRR run yet. Click Refresh forecast to retrieve one.');renderMissing();}
    renderTrend();renderNearby(nearby);renderStorage(storage);
    await loadHistoryOptions();
  }catch(error){notice('Saved data could not be loaded: '+error.message,'error');renderMissing();}
}
function renderMissing(){setText('opportunityScore','— /100');setText('opportunityLabel','No live forecast cached');setText('opportunityExplanation','Click Refresh forecast to download issued NOAA HRRR data. No illustrative forecast numbers are substituted.');setText('explorerTime','No issued-run forecast yet');setText('explorerRun','Forecast cache empty');setText('bestHours','No available forecast hours.');setText('forecastMetricsExtended','');}
function selectAtmosphereFrame(index){
  if(!state.future.length)return;
  state.index=Math.max(0,Math.min(state.future.length-1,Math.round(Number(index)||0)));
  $('explorerSlider').value=String(state.index);
  const currentHourData=state.future[state.index];
  setText('explorerTime',timeLabel(currentHourData.timestamp));
  setText('explorerRun',`NOAA HRRR issued ${timeLabel(currentHourData.run_utc)} · F${currentHourData.lead_hours}`);
  renderHero(currentHourData);renderNWS(currentHourData);
  renderCloudScene(currentHourData);
  renderFoothillsTransect(currentHourData);
  renderMetrics(currentHourData);
  renderEvidence(currentHourData);
  const date=localDay(currentHourData.timestamp);if(date!==state.solarDate)loadSolar(date);
  highlightTrend();
}
function stepAtmosphere(dir){selectAtmosphereFrame(state.index+dir);}
function toggleAtmospherePlay(){if(state.playing){clearInterval(state.playing);state.playing=null;setText('explorerPlay','Play');return;}if(state.future.length<2)return;setText('explorerPlay','Pause');state.playing=setInterval(()=>selectAtmosphereFrame((state.index+1)%state.future.length),1700);}
function renderHero(r){
  const score=num(r.opportunity_score);const display=score===null?'—':String(Math.round(score));
  $('opportunityScore').innerHTML=`${display}<span>/100</span>`;
  setText('opportunityLabel',r.opportunity_label||'Insufficient atmospheric data');
  setText('opportunityExplanation',r.opportunity_note||'Uncalibrated forecast-based index, not an observed inversion.');
  setText('scoreTime',timeLabel(r.timestamp));setText('forecastVintage',`HRRR F${r.lead_hours}`);
  $('opportunityGauge').style.setProperty('--angle',`${score===null?0:score*3.6}deg`);
  setText('heroLow',fmt(r.lowClouds,'%'));
  setText('heroHigh',`${fmt(r.midClouds,'%')} / ${fmt(r.highClouds,'%')}`);
  setText('heroRh',fmt(r.opportunity_evidence?.summit_rh_pct,'%'));
  setText('heroTemp',fmt(r.tempDelta,'°C',1));
  const best=state.future.filter(x=>num(x.opportunity_score)!==null&&localDay(x.timestamp)===localDay(r.timestamp)).slice().sort((a,b)=>b.opportunity_score-a.opportunity_score);
  $('bestHours').innerHTML=best.length?best.slice(0,4).map(x=>`<button class="btn secondary sm" style="margin:3px" onclick="selectAtmosphereFrame(${state.future.indexOf(x)})">${escapeHTML(shortTime(x.timestamp))} · ${fmt(x.opportunity_score)}/100</button>`).join(''):'No complete score for this date.';
}
function renderNWS(r){
 const entries=state.nws?.hours||[],target=new Date(r.timestamp).getTime();
 const match=entries.find(h=>{const when=new Date(h.timestamp_utc).getTime();return target>=when&&target<when+3600000;});
 if(!match){setText('nwsSummary','No matching cached NWS hourly guidance. Refresh to retrieve a separate public forecast.');return;}
 const old=new Date(state.nws.fetched_utc).getTime();
 const age=Number.isFinite(old)&&Date.now()-old>18*3600000?'<span class="small" style="color:#f1c47b"> · Cached guidance may be stale</span>':'';
 const details=[match.summary,fmt(match.temperature,match.temperature_unit==='F'?'°F':'°'+match.temperature_unit),match.wind_speed,match.wind_direction].filter(Boolean);
 $('nwsSummary').innerHTML=`<strong>${escapeHTML(details.join(' · '))}</strong>${age}<div class="help">Separate NWS guidance (not included in the index). ${safeLink(state.nws?.source_url,'Original NWS hourly forecast')}</div>`;
}
function renderCloudScene(r){
  const lo=num(r.lowClouds),mi=num(r.midClouds),hi=num(r.highClouds);
  $('sceneFog').setAttribute('opacity',lo===null?0:Math.min(.92,Math.max(0,lo/100)));
  $('sceneMid').setAttribute('opacity',mi===null?0:Math.min(.95,mi/100));
  $('sceneHigh').setAttribute('opacity',hi===null?0:Math.min(.96,hi/100));
  const height=num(r.scenic_profile_drying_transition_ft_msl);
  let y=216;
  if(height!==null&&height>=5400&&height<=9400){y=Math.max(75,Math.min(315,335-(height-5400)*.066));$('sceneDrying').setAttribute('opacity','0.8');$('sceneDrying').setAttribute('y1',y);$('sceneDrying').setAttribute('y2',y);}else{$('sceneDrying').setAttribute('opacity','0');}
  $('sceneFogBody').setAttribute('y',y);$('sceneFogBody').setAttribute('height',360-y);
  $('sceneFogEdge').setAttribute('transform',`translate(0 ${y-215})`);
  const hr=Number(new Intl.DateTimeFormat('en-US',{timeZone:TZ,hour:'2-digit',hour12:false}).format(new Date(r.timestamp)));
  $('sceneSun').setAttribute('opacity',hr>=6&&hr<=18?'1':'0.04');
  $('sceneTitle').textContent=`HRRR low ${fmt(lo,'%')} · mid ${fmt(mi,'%')} · high ${fmt(hi,'%')}`;
  $('explorerNotice').textContent=height!==null?`Dashed line: forecast RH drying transition near ${fmt(height,' ft')} MSL. This is a humidity proxy, NOT cloud top. The opaque low deck is an illustration, not an observed three-dimensional cloud field.`:'Low-cloud opacity uses NOAA HRRR low-cloud fraction. Its vertical top is unknown; the drawn boundary is schematic and NOT cloud top.';
}
function renderTrend(){
 const data=state.future;const svg=$('forecastTrend');if(!data.length){svg.innerHTML='';return;}
 const W=900,H=195,l=35,r=18,t=15,b=34,dx=(W-l-r)/Math.max(1,data.length-1),y=v=>H-b-v*(H-b-t)/100;
 const poly=(key,color)=>{const values=data.map((x,i)=>({v:num(x[key]),i}));let parts=[],segment=[];for(const p of values){if(p.v===null){if(segment.length)parts.push(segment);segment=[];}else segment.push(`${l+dx*p.i},${y(p.v)}`);}if(segment.length)parts.push(segment);return parts.map(pts=>`<polyline points="${pts.join(' ')}" stroke="${color}" stroke-width="3" fill="none" stroke-linejoin="round"/>`).join('');};
 let markup=`<g font-size="11" fill="#8eb3b9">${[0,50,100].map(v=>`<line x1="${l}" x2="${W-r}" y1="${y(v)}" y2="${y(v)}" stroke="#37515a" stroke-dasharray="4 5"/><text x="4" y="${y(v)+4}">${v}</text>`).join('')}</g>${poly('opportunity_score','#79dec6')}${poly('lowClouds','#6bb2e2')}`;
 markup+=data.map((item,i)=>`<circle data-trend-index="${i}" cx="${l+dx*i}" cy="${y(num(item.opportunity_score)??0)}" r="4.5" fill="#79dec6" stroke="#0d2731" stroke-width="1"/>`).join('');
 markup+=`<g font-size="10" fill="#9cb8bf"><text x="${l}" y="${H-8}">${escapeHTML(shortTime(data[0].timestamp))}</text><text x="${W/2}" y="${H-8}" text-anchor="middle">${escapeHTML(fmtDate(data[Math.floor(data.length/2)].timestamp,{month:'short',day:'numeric',hour:'numeric'}))}</text><text x="${W-r}" y="${H-8}" text-anchor="end">${escapeHTML(fmtDate(data[data.length-1].timestamp,{month:'short',day:'numeric',hour:'numeric'}))}</text></g>`;
 svg.innerHTML=markup;
 svg.querySelectorAll('[data-trend-index]').forEach(el=>el.addEventListener('click',()=>selectAtmosphereFrame(Number(el.dataset.trendIndex))));
}
function highlightTrend(){document.querySelectorAll('[data-trend-index]').forEach(el=>{const active=+el.dataset.trendIndex===state.index;el.setAttribute('r',active?7:4.5);el.setAttribute('stroke',active?'#fff':'#0d2731');});}
function metricColor(v){if(v===null)return '#24333a';return `hsl(${Math.max(10,175-v*1.25)} 48% ${Math.max(25,65-v*.3)}%)`;}
function pointsFor(r){return r.foothills_transect?.points||[];}
function changeTransectMetric(metric){state.transectMetric=metric;const r=state.future[state.index];if(r)renderFoothillsTransect(r);}
function renderFoothillsTransect(currentHourData){
 const data=currentHourData?.foothills_transect;const points=pointsFor(currentHourData);
 if(!points.length){$('mapPoints').innerHTML='<text x="315" y="175" fill="#bad5d3" font-size="16" text-anchor="middle">Spatial forecast not cached for this hour</text>';setText('transectHeatmap','');setText('transectCells','Distinct HRRR cells: unknown');setText('transectProvenance','Fetch the selected hour’s named-point HRRR data; no synthetic map values are shown.');$('transectSelectedDetails').innerHTML='';$('transectFetchButton').disabled=false;return;}
 $('transectFetchButton').disabled=true;
 const x=lon=>35+(lon+105.33)/.32*560,y=lat=>20+(40.065-lat)/.12*292;
 const chosen=state.selectedLocation;
 $('mapPoints').innerHTML=points.map(p=>{const color=metricColor(num(p[state.transectMetric]));return `<g data-point="${escapeHTML(p.id)}" tabindex="0" role="button" aria-label="View ${escapeHTML(p.name)}" ><circle cx="${x(p.longitude)}" cy="${y(p.latitude)}" r="${p.id===chosen?11:8}" fill="${color}" stroke="${p.id===chosen?'#fff':'#a6d8d3'}" stroke-width="${p.id===chosen?3:1}"/><text x="${x(p.longitude)+12}" y="${y(p.latitude)-6}" fill="#e5f5ee" font-size="11">${escapeHTML(p.name)}</text></g>`}).join('');
 $('mapPoints').querySelectorAll('[data-point]').forEach(el=>{const select=()=>{state.selectedLocation=el.dataset.point;renderFoothillsTransect(currentHourData);};el.addEventListener('click',select);el.addEventListener('keydown',e=>{if(e.key==='Enter')select();});});
 setText('transectCells',`Unique model-grid cells: ${data.unique_model_cells??'unknown'} of ${points.length} named places`);
 setText('transectProvenance',data.note||'Nearest HRRR model grid cells; these are not camera observations or precise slope forecasts.');
 const p=points.find(x=>x.id===chosen)||points[0];state.selectedLocation=p.id;
 const items=[['Selected location',p.name],['Model terrain',fmt(p.grid_terrain_ft_msl,' ft')],['Low cloud',fmt(p.low_cloud_pct,'%')],['Mid cloud',fmt(p.mid_cloud_pct,'%')],['High cloud',fmt(p.high_cloud_pct,'%')],['RH at 8,133 ft',fmt(p.rh_at_8133ft_pct,'%')]];
 $('transectSelectedDetails').innerHTML=items.map(([k,v])=>`<div class="metric"><small>${escapeHTML(k)}</small><b style="font-size:14px">${escapeHTML(v)}</b></div>`).join('');
 const levels=[5500,6500,7258,8133,9000];
 function rhAt(layers,feet){if(!Array.isArray(layers))return null;for(let i=1;i<layers.length;i++){const a=layers[i-1],b=layers[i];if(feet>=a.height_ft_msl&&feet<=b.height_ft_msl&&b.height_ft_msl>a.height_ft_msl)return a.rh_pct+(b.rh_pct-a.rh_pct)*(feet-a.height_ft_msl)/(b.height_ft_msl-a.height_ft_msl);}return null;}
 let cells='<div class="heat-cell">Place</div>'+levels.map(z=>`<div class="heat-cell">${(z/1000).toFixed(1)}k ft</div>`).join('');
 points.forEach(p=>{cells+=`<div class="heat-label">${escapeHTML(p.name)}</div>`;levels.forEach(level=>{const v=rhAt(p.humidity_by_height,level);cells+=`<div class="heat-cell" style="background:${metricColor(v)};color:#fff">${fmt(v,'%',0)}</div>`;});});
 $('transectHeatmap').innerHTML='<div class="heat-table">'+cells+'</div><p class="help">Colored percentages: RH interpolated between reported model pressure levels. Blank = insufficient vertical information, not clear air. This is NOT cloud top.</p>';
}
function renderMetrics(r){
 const e=r.opportunity_evidence||{},o=r;
 const items=[['Surface temperature',fmt(o.surfTemp,'°C',1)],['Dew point',fmt(o.dewPoint,'°C',1)],['Surface RH',fmt(o.rh,'%',0)],['Low cloud',fmt(o.lowClouds,'%')],['Mid cloud',fmt(o.midClouds,'%')],['High cloud',fmt(o.highClouds,'%')],['10 m wind',fmt(o.windSpeed,' mph',1)],['Wind direction',fmt(o.windDir,'°',0)],['Predicted visibility',fmt(num(o.forecast_visibility_m)===null?null:o.forecast_visibility_m/1609.344,' mi',1)],['Boundary-layer height',fmt(o.forecast_boundary_layer_height_m,' m',0)],['Forecast cloud base',fmt(o.forecast_cloud_base_ft_msl,' ft')],['Whole-column cloud top',fmt(o.forecast_cloud_top_ft_msl,' ft')],['300 m warming proxy',fmt(o.tempDelta,'°C',1)],['Humidity drying proxy',fmt(o.scenic_profile_drying_transition_ft_msl,' ft')],['Model terrain',fmt(o.forecast_terrain_ft_msl,' ft')],['Upper-sky factor',fmt(o.scenic_upper_clear_factor,'%',0)],['Low-cloud setup (diagnostic)',fmt(o.heuristic_score,'/100')],['Named HRRR cells',fmt(e.unique_hrrr_cells,'',0)]];
 $('forecastMetricsExtended').innerHTML=items.map(([k,v])=>`<div class="metric"><small>${escapeHTML(k)}</small><b>${escapeHTML(v)}</b></div>`).join('');
 const f=r.forecast_source||{};$('forecastEvidenceSource').innerHTML=[safeLink(f.surface_inventory_url,'NOAA HRRR surface GRIB inventory'),safeLink(f.pressure_inventory_url,'NOAA HRRR vertical GRIB inventory'),safeLink(f.model_documentation_url,'HRRR documentation')].join('');
}
function renderEvidence(r){
 const e=r.opportunity_evidence||{},notes=e.data_issues||[];
 const tests=[['Valley low cloud',fmt(e.boulder_low_cloud_pct,'%')],['High and middle layers',`${fmt(e.middle_cloud_pct,'%')} mid · ${fmt(e.high_cloud_pct,'%')} high`],['RH at 8,133 feet',fmt(e.summit_rh_pct,'%')],['RH drying transition',fmt(e.drying_transition_ft_msl,' ft')],['Spatial modifier',e.spatial_modifier===null?'Not available':fmt(e.spatial_modifier*100,'%',1)],['Score algorithm',r.opportunity_version||'Unknown']];
 $('opportunityEvidence').innerHTML=tests.map(([k,v])=>`<div class="evidence"><span class="muted">${escapeHTML(k)}</span><b>${escapeHTML(v)}</b></div>`).join('')+`<p class="help">${notes.length?notes.map(x=>`• ${escapeHTML(x)}`).join('<br>'):'Forecast inputs available; still unvalidated against actual summit photos.'}</p>`;
}
async function loadSolar(date){if(!date)return;state.solarDate=date;setText('solarDate',date+' · Boulder local');try{const data=await getJSON('/api/solar?date_local='+encodeURIComponent(date));if(state.solarDate!==date)return;const pairs=[['Civil dawn',data.civil_dawn],['Sunrise',data.sunrise],['Golden hour ends',data.morning_golden_end],['Golden hour starts',data.evening_golden_start],['Sunset',data.sunset],['Civil dusk',data.civil_dusk]];$('solarCards').innerHTML=pairs.map(([name,value])=>`<div class="solaritem"><div class="micro">${name}</div><strong>${escapeHTML(shortTime(value))}</strong></div>`).join('');}catch(e){setText('solarCards','Sun times unavailable: '+e.message);}}
function renderNearby(data){let stations=data?.stations||[];if(!stations.length){$('nearbyStations').innerHTML='<div class="empty">No recent airport reports cached. Click Refresh forecast.</div>';return;}let at=data.retrieved_utc?timeLabel(data.retrieved_utc):'unknown';setText('nearbyStatus',`Last refreshed ${at}. Actual airport METARs, not measured mountain fog height.`);$('nearbyStations').innerHTML=stations.map(p=>{let sky=(p.sky_layers||[]).map(x=>x.coverage+(num(x.height_ft_agl)===null?'':' '+fmt(x.height_ft_agl,' ft'))).join(' · ');return `<div class="station"><span class="micro">${escapeHTML(p.station)} · ${escapeHTML(timeLabel(p.timestamp_utc))}</span><strong>${escapeHTML(p.name)}</strong><div class="evidence"><span>Visibility</span><b>${escapeHTML(fmt(p.visibility_miles,' mi',1))}</b></div><div class="evidence"><span>Temperature / RH</span><b>${escapeHTML(fmt(p.temperature_f,'°F'))} / ${escapeHTML(fmt(p.relative_humidity_pct,'%'))}</b></div><div class="small muted">Sky: ${escapeHTML(sky||'Not reported')} ${escapeHTML(p.weather_codes||'')}</div>${p.metar?`<details><summary>Raw METAR</summary><p class="report mono">${escapeHTML(p.metar)}</p></details>`:''}</div>`;}).join('');}
function renderStorage(data){if(!data){setText('storageSummary','Storage information unavailable.');return;}let files=(data.files||[]).slice().sort((a,b)=>b.size_mb-a.size_mb);$('storageSummary').innerHTML=`<div class="evidence"><span class="muted">Archived forecast snapshots</span><b>${fmt(data.history_snapshots)}</b></div>`+files.slice(0,8).map(x=>`<div class="evidence"><span class="muted">${escapeHTML(x.name)}</span><b>${fmt(x.size_mb,' MB',2)}</b></div>`).join('')+'<div class="help">Seven-day disposable forecast cache; no automatic deletion of historical predictions or original training files.</div>';}
async function loadHistoryOptions(){try{let j=await getJSON('/api/history');let times=j.event_times_utc||[];state.historyTimes=times;const el=$('historySelect');const existing=state.historyEvent&&times.includes(state.historyEvent)?state.historyEvent:null;const newChoice=existing||(times.find(t=>{let h=Number(new Intl.DateTimeFormat('en-US',{hour:'numeric',hour12:false,timeZone:TZ}).format(new Date(t)));return h===7||h===8;})||times[0]||'');el.innerHTML='<option value="">Select past hour</option>'+times.map(t=>`<option value="${escapeHTML(t)}">${escapeHTML(timeLabel(t))}</option>`).join('');if(newChoice){el.value=newChoice;await loadHistory(newChoice);}else{state.historyEvent=null;$('historyCards').innerHTML='<div class="empty">No historical forecast records saved yet.</div>';}}catch(error){setText('historyNote','History unavailable: '+error.message);}}
async function loadHistory(eventUTC){state.historyEvent=eventUTC||null;if(!eventUTC)return;try{const j=await getJSON('/api/history?event_utc='+encodeURIComponent(eventUTC));if(state.historyEvent!==eventUTC)return;setText('historyNote',`${timeLabel(eventUTC)} · captured forecasts vs later reconstructions · five as-of cutoffs`);renderHistoricalCards(j.comparisons||[]);renderActual(j.observation);renderHistoryDisagreement(j.comparisons||[]);}catch(error){setText('historyNote',error.message);}}
function renderHistoricalCards(entries){$('historyCards').innerHTML=entries.map(({hours_before_event:h,forecast:f})=>{if(!f)return `<article class="history-card"><span class="micro">T−${h} h</span><p>Not downloaded</p><b>—</b><p>Click Fill missing predictions.</p></article>`;let overall=num(f.opportunity_score);let upper=f.scenic_indicators||{};let source=f.forecast_source||{};return `<article class="history-card"><span class="micro">T−${h} h · ${escapeHTML(f.origin||'')}</span><b>${overall===null?'—':fmt(overall,'/100')}</b><p>${overall===null?'Archived under an older scoring version':escapeHTML(f.opportunity_label||'Boulder opportunity')}</p><div class="evidence"><span>Low cloud</span><b>${fmt(f.lowClouds??upper.low_cloud_cover_pct,'%')}</b></div><div class="evidence"><span>Middle</span><b>${fmt(upper.mid_cloud_cover_pct,'%')}</b></div><div class="evidence"><span>High</span><b>${fmt(upper.high_cloud_cover_pct,'%')}</b></div><div class="small muted" style="margin-top:8px">HRRR F${fmt(f.lead_hours)} · ${escapeHTML(shortTime(f.run_utc))} run</div>${source.surface_inventory_url?`<div class="small">${safeLink(source.surface_inventory_url,'NOAA original fields')}</div>`:''}<details><summary>Raw forecast evidence</summary><p class="small muted">Low-cloud index ${fmt(f.heuristic_score,'/100')} · inversion signal: ${fmt(f.tempDelta,'°C',1)} · wind ${fmt(f.windSpeed,' mph',1)}. A reconstruction is not a contemporaneous website capture.</p></details></article>`;}).join('');}
function renderActual(r){const el=$('actualObservation');if(!r){el.textContent='No independent KBDU METAR report cached for that hour. Refresh forecast to retrieve recent airport observations; lack of a report does not mean clear weather.';return;}el.innerHTML=`<b>Observed at Boulder airport:</b> ${r.observed_low_ceiling===null?'Low ceiling unknown':r.observed_low_ceiling?'Low ceiling reported':'No low ceiling reported'} · Fog-like event: ${r.observed_fog===null?'unknown':r.observed_fog?'reported':'not reported'} · Visibility: ${fmt(r.visibility_miles,' mi',1)} · Ceiling: ${fmt(r.observed_cloud_base_ft_msl,' ft MSL')}<p class="help">${escapeHTML(r.meaning||'Actual airport weather is not a summit observation.')}</p>`;}
function renderHistoryDisagreement(entries){const vals=key=>entries.map(e=>num(e.forecast?.scenic_indicators?.[key])).filter(v=>v!==null);let ranges=[['Low clouds','low_cloud_cover_pct'],['Middle clouds','mid_cloud_cover_pct'],['High clouds','high_cloud_cover_pct']].map(([name,k])=>{let x=vals(k);return x.length>=2?`${name}: ${fmt(Math.min(...x),'%')}–${fmt(Math.max(...x),'%')}`:null;}).filter(Boolean);setText('historyDisagreement',ranges.length?'Forecast revisions across these HRRR runs: '+ranges.join(' · '):'Insufficient matching forecast vintages to evaluate cloud disagreement.');}
async function fillHistory(){if(!state.historyEvent){notice('Choose a past hour before requesting its forecast vintages.');return;}const btn=$('historyFill');btn.disabled=true;try{const job=await getJSON('/api/history/reconstruct',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event_utc:state.historyEvent})});setText('historyNote','Fetching archived HRRR forecasts for selected hour…');for(let i=0;i<180;i++){await new Promise(resolve=>setTimeout(resolve,1400));const progress=await getJSON('/api/history/reconstruct/status?job_id='+encodeURIComponent(job.id));setText('historyNote',`Historical reconstruction: ${(progress.progress||[]).length}/5 checked`);if(progress.state==='complete'){await loadHistory(state.historyEvent);return;}}throw Error('Request still running. Check again later.');}catch(e){notice('History request: '+e.message,'error');}finally{btn.disabled=false;}}
async function fetchSelectedTransect(){const row=state.future[state.index];if(!row)return;const btn=$('transectFetchButton');btn.disabled=true;try{const job=await getJSON('/api/transect/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({timestamp:row.timestamp})});setText('transectFetchStatus','Downloading selected HRRR spatial profile…');for(let i=0;i<120;i++){await new Promise(resolve=>setTimeout(resolve,1500));const status=await getJSON('/api/transect/refresh/status?job_id='+encodeURIComponent(job.id));setText('transectFetchStatus',status.message||status.state);if(status.state==='complete'){await loadAll();return;}if(status.state==='error')throw Error(status.message);}throw Error('Spatial download continues. Reload after completion.');}catch(e){setText('transectFetchStatus','Unable to load: '+e.message);}finally{btn.disabled=false;}}
async function refreshEverything(){if(state.loading)return;state.loading=true;const btn=$('refreshAllButton');btn.disabled=true;let payload=state.historyEvent?{event_utc:state.historyEvent}:{};try{let job=await getJSON('/api/refresh/all',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});notice('Downloading issued NOAA HRRR forecasts; existing saved results remain visible.');for(let i=0;i<350;i++){await new Promise(resolve=>setTimeout(resolve,1800));let s=await getJSON('/api/refresh/all/status?job_id='+encodeURIComponent(job.id));setText('refreshProgress',s.message||s.stage||'Refreshing…');if(s.state==='complete'){let failures=(s.results||[]).filter(x=>x.status==='error');await loadAll();if(failures.length)notice(`Refresh partially completed. ${failures.length} source step(s) failed: ${failures.map(x=>x.stage).join(', ')}. Existing forecasts were preserved.`,'error');setText('refreshProgress','Refresh complete · '+new Date().toLocaleTimeString());return;}}throw Error('Network job continues; check the status and reload later.');}catch(e){notice('Refresh failed: '+e.message+'. Cached forecasts remain available.','error');}finally{state.loading=false;btn.disabled=false;}}
window.addEventListener('DOMContentLoaded',()=>loadAll());
