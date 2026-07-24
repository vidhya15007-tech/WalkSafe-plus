// ---------------- Emergency Alert ----------------
async function sendAlert(){
  const res = await fetch("/alert",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({})});
  try{
    const data = await res.json();
    if(data.status==="success") alert("Emergency email sent successfully!");
    else alert("Alert failed: "+(data.reason||JSON.stringify(data.errors||data)));
  }catch{alert("Unexpected response from server.");}
}

// ---------------- Geocoding ----------------
async function getCoordinates(address){
  const url=`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(address)}`;
  const resp = await fetch(url);
  const data = await resp.json();
  if(!data||data.length===0) throw new Error("Address not found: "+address);
  return [parseFloat(data[0].lat),parseFloat(data[0].lon)];
}

// ---------------- OpenRouteService ----------------
const ORS_API_KEY="YOUR_OPENROUTESERVICE_KEY";

async function getRoute(src,dst,waypoints=[]){
  const points=[src].concat(waypoints).concat([dst]);
  try{
    const coords=points.map(p=>[p[1],p[0]]);
    const url="https://api.openrouteservice.org/v2/directions/foot-walking/geojson";
    const resp=await fetch(url,{
      method:"POST",
      headers:{"Authorization":ORS_API_KEY,"Content-Type":"application/json"},
      body:JSON.stringify({coordinates:coords})
    });
    const data=await resp.json();
    return data.features[0].geometry.coordinates.map(c=>[c[1],c[0]]);
  }catch{return points;}
}

// ---------------- Map Initialization ----------------
async function initMapWithRoutes(source,destination){
  const fallbackSrc=[13.0827,80.2707], fallbackDst=[13.0674,80.2376];
  const src=await getCoordinates(source).catch(()=>fallbackSrc);
  const dst=await getCoordinates(destination).catch(()=>fallbackDst);

  const map=L.map('map').setView(src,13);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19}).addTo(map);

  const policeStations=[{coords:[13.082,80.27],info:"Police Station",color:"blue"}];
  const hospitals=[{coords:[13.08,80.26],info:"Hospital",color:"red"}];
  const streetLights=[{coords:[13.078,80.265],info:"Street Light",color:"yellow"}];
  const cctvs=[{coords:[13.079,80.263],info:"CCTV",color:"green"}];

  const shortestCoords=await getRoute(src,dst);
  const safestCoords=await getRoute(src,dst,policeStations.map(p=>p.coords));

  L.polyline(shortestCoords,{color:'blue',weight:4,opacity:0.7}).addTo(map).bindPopup("Shortest Route");
  L.polyline(safestCoords,{color:'green',weight:4,opacity:0.7}).addTo(map).bindPopup("Safest Route");

  [hospitals,streetLights,cctvs].flat().forEach(p=>{
    L.circleMarker(p.coords,{radius:8,color:p.color,fillColor:p.color,fillOpacity:0.8}).addTo(map).bindPopup(p.info);
  });
  policeStations.forEach(p=>L.circleMarker(p.coords,{radius:10,color:p.color,fillColor:p.color,fillOpacity:0.8}).addTo(map).bindPopup(p.info));

  L.marker(src).addTo(map).bindPopup("Source: "+source).openPopup();
  L.marker(dst).addTo(map).bindPopup("Destination: "+destination);

  const legend=L.control({position:'bottomright'});
  legend.onAdd=function(){
    const div=L.DomUtil.create('div','info legend');
    div.innerHTML=`
      <h4>Legend</h4>
      <i style="background:red;width:12px;height:12px;border-radius:50%;display:inline-block;margin-right:5px;"></i> Hospital<br>
      <i style="background:blue;width:12px;height:12px;border-radius:50%;display:inline-block;margin-right:5px;"></i> Police Station<br>
      <i style="background:yellow;width:12px;height:12px;border-radius:50%;display:inline-block;margin-right:5px;"></i> Street Light<br>
      <i style="background:green;width:12px;height:12px;border-radius:50%;display:inline-block;margin-right:5px;"></i> CCTV<br>
      <span style="color:blue;font-weight:bold">Blue Line</span>: Shortest Route<br>
      <span style="color:green;font-weight:bold">Green Line</span>: Safest Route`;
    return div;
  };
  legend.addTo(map);
  map.fitBounds(L.latLngBounds(shortestCoords.concat(safestCoords,policeStations.map(p=>p.coords),[src,dst])).pad(0.2));
}
