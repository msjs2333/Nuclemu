const ink = "#394354";
const accent = "#3859d9";
const particle = "#bb5735";
function line(g, points, color = ink, weight = 1.2) {
  g.beginPath();
  points.forEach(([x, y], i) => i ? g.lineTo(x, y) : g.moveTo(x, y));
  g.strokeStyle = color;
  g.lineWidth = weight;
  g.stroke();
}

function prepare(canvas) {
  const width=canvas.clientWidth, height=canvas.clientHeight;
  if(!width || !height) return;
  const dpr=window.devicePixelRatio||1;
  const w=Math.round(width*dpr), h=Math.round(height*dpr);
  if(canvas.width!==w) canvas.width=w;
  if(canvas.height!==h) canvas.height=h;
  const g=canvas.getContext("2d");
  g.setTransform(dpr,0,0,dpr,0,0);
  g.clearRect(0,0,width,height);
  return {g,width,height};
}

function connect(g, start, end, kind, detour) {
  const dx=end.x-start.x, dir=dx>=0?1:-1;
  const x1=start.x+dir*(dir>0?start.right:start.left), x2=end.x-dir*(dir>0?end.left:end.right);
  const color=kind==="particle"?particle:accent;
  const y1=start.outY;
  const points=[[x1,y1]];
  if(detour && kind!=="particle") {
    const bend=Math.min(y1,end.y)-Math.max(start.left,end.left)*1.15;
    points.push([x1+dir*4,y1],[x1+dir*4,bend],[x2-dir*6,bend],[x2-dir*6,end.y]);
  } else if(kind!=="particle" && Math.abs(end.y-y1)>1) {
    points.push([(x1+x2)/2,y1],[(x1+x2)/2,end.y]);
  }
  points.push([x2,end.y]);
  g.save(); g.setLineDash(kind==="particle"?[4,3]:[]); line(g,points,color,1.6);
  g.setLineDash([]);line(g,[[x2-dir*4,end.y-3],[x2,end.y],[x2-dir*4,end.y+3]],color,1.6);g.restore();
}

function routes(g, edges, positions, labels=false) {
  const nodes = [...positions.values()];
  for(const edge of edges) {
    const src=positions.get(edge.source), dst=positions.get(edge.target);
    if(!src || !dst) continue;
    const detour=edge.kind!=="particle" && nodes.some(p=>p.x>Math.min(src.x,dst.x) && p.x<Math.max(src.x,dst.x));
    connect(g,src,dst,edge.kind,detour);
    if(labels && !detour && dst.x>src.x && edge.label) {
      const start=src.x+src.right, end=dst.x-dst.left;
      g.save();
      g.font='13px "Nuclemu Lab Sans", "Noto Sans SC", "Microsoft YaHei", sans-serif';
      if(end-start>g.measureText(edge.label).width+8) {
        g.fillStyle="#101010";
        g.textAlign="center"; g.fillText(edge.label,(start+end)/2,Math.min(src.outY,dst.y)-9);
      }
      g.restore();
    }
  }
}

// Images, named fallback nodes and their connections use the same layout.
const rigConnections = new WeakMap();
export function drawConnections(canvas, connections) {
  let state = rigConnections.get(canvas);
  if (!state) {
    state = {connections, frame: 0};
    rigConnections.set(canvas, state);
    canvas.addEventListener('rig-layout', () => drawConnections(canvas, state.connections));
  }
  state.connections = connections;
  // Resize, image loading and the shared layout may request the same drawing.
  // Read the final geometry once, after all figures have placed their images.
  if (!state.frame) state.frame = requestAnimationFrame(() => {
    state.frame = 0;
    if (canvas.isConnected) paintConnections(canvas, state.connections);
  });
}

function paintConnections(canvas, connections) {
  const surface = prepare(canvas);
  if (!surface) return;
  const origin = canvas.getBoundingClientRect();
  const positions = new Map();
  for (const node of canvas.parentElement.querySelectorAll("[data-node]")) {
    const rect = node.getBoundingClientRect();
    const half = rect.width / 2;
    positions.set(node.dataset.node, {
      x: rect.left - origin.left + half,
      y: rect.top - origin.top + rect.height * Number(node.dataset.beamY ?? .5),
      outY: rect.top - origin.top + rect.height * Number(node.dataset.outY ?? .5),
      left: half - rect.width * Number(node.dataset.inX ?? 0),
      right: rect.width * Number(node.dataset.outX ?? 1) - half,
    });
  }
  routes(surface.g, connections, positions, canvas.classList.contains("wiring"));
}

export const margin={left:62,right:27,top:30,bottom:43};

export function spectrumExtent(series,channels) {
  let first=channels, last=-1, maximum=0;
  for(const {counts,divisor} of series) {
    if(!(divisor>0)) continue;
    for(let channel=0;channel<counts.length;channel++){
      const count=counts[channel];
      if(count<=0) continue;
      first=Math.min(first,channel);
      last=Math.max(last,channel);
      maximum=Math.max(maximum,count/divisor);
    }
  }
  if(last<first) return {range:[0,channels-1],maximum:0};
  const padding=Math.max(3,Math.ceil((last-first+1)*0.08));
  return {range:[Math.max(0,first-padding),Math.min(channels-1,last+padding)],maximum};
}

export function pointerChannels(canvas, [first, last]) {
  const left = canvas.getBoundingClientRect().left + canvas.clientLeft + margin.left;
  const width = Math.max(1, canvas.clientWidth - margin.left - margin.right);
  return clientX => {
    const fraction = Math.max(0, Math.min(1, (clientX - left) / width));
    return Math.round(first + fraction * (last - first));
  };
}

function axisTick(value) {
  if(Math.abs(value)>=1e5 || (value!==0 && Math.abs(value)<.01))return value.toExponential(1);
  return Number(value.toPrecision(4)).toString();
}

function tickSpacing(target) {
  const order=10**Math.floor(Math.log10(target));
  return [1,2,5,10].find(factor=>factor*order>=target)*order;
}

function horizontalTicks([lo,hi],energy,width) {
  const goal=Math.max(2,Math.min(10,Math.floor(width/82)));
  const span=hi-lo;
  if(span===0) return [{channel:lo,label:energy?axisTick(energy(lo)):String(lo)}];
  if(energy) {
    const start=energy(lo), end=energy(hi);
    if(start===end) return [{channel:lo,label:axisTick(start)}];
    const energySpan=Math.abs(end-start);
    let step=tickSpacing(energySpan/goal);
    // A coarse rounded step can leave just one labeled division on a phone.
    if(energySpan/step<2) step/=2;
    const first=Math.ceil(Math.min(start,end)/step);
    const count=Math.floor(Math.max(start,end)/step)-first+1;
    const ticks=[];
    for(let i=0;i<Math.min(count,goal+2);i++){
      const value=(first+i)*step;
      ticks.push({channel:lo+span*(value-start)/(end-start),label:axisTick(value)});
    }
    if(ticks.length>=2 && new Set(ticks.map(tick=>tick.label)).size===ticks.length) return ticks;
    return [{channel:lo,label:String(start)},{channel:hi,label:String(end)}];
  }
  const step=2**Math.max(0,Math.ceil(Math.log2(span/goal)));
  const ticks=[{channel:lo,label:String(lo)}];
  for(let channel=(Math.floor(lo/step)+1)*step;channel<hi;channel+=step) {
    if((channel-lo)*width/span<42 || (hi-channel)*width/span<42) continue;
    ticks.push({channel,label:String(channel)});
  }
  ticks.push({channel:hi,label:String(hi)});
  return ticks;
}

export function drawSpectrum(canvas,series,n,roi,energy,label,range,maximum) {
  const surface=prepare(canvas);if(!surface || n<1)return;
  const {g,width,height}=surface;
  const left=margin.left,right=width-margin.right,top=margin.top,bottom=height-margin.bottom;
  if(right<=left || bottom<=top)return;
  let high=maximum||1;
  let yStep=tickSpacing(high/5);
  if(label==="每道计数")yStep=Math.max(yStep,1);
  const yTicks=Math.ceil(high/yStep);
  high=yTicks*yStep;
  const [first,last]=range;
  const x=i=>first===last?(left+right)/2:left+(right-left)*(i-first)/(last-first);
  const y=v=>bottom-(bottom-top)*v/high;
  g.font='13px "Nuclemu Lab Sans", "Noto Sans SC", "Microsoft YaHei", sans-serif';
  g.textAlign="left";g.fillStyle="#101010";g.fillText(label,left,16);
  const [lo,hi]=roi;
  if((lo>0 || hi<n-1) && hi>=first && lo<=last) {
    const start=x(Math.max(first,lo)), end=x(Math.min(last,hi));
    g.fillStyle="rgba(56,89,217,.065)";g.fillRect(start,top,Math.max(1,end-start),bottom-top);
    if(lo>=first) line(g,[[start,top],[start,bottom]],"#aab9eb",1);
    if(hi<=last) line(g,[[end,top],[end,bottom]],"#aab9eb",1);
  }
  g.textAlign="right";g.fillStyle="#101010";
  for(let i=0;i<=yTicks;i++) {
    const value=yStep*i, tickY=y(value);
    line(g,[[left,tickY],[right,tickY]],"#e2e6ef",1);
    g.fillText(axisTick(value),left-8,tickY+4);
  }
  const ticks=horizontalTicks(range,energy,right-left);
  for(const tick of ticks){
    if(tick.channel<=first||tick.channel>=last) continue;
    const column=x(tick.channel);
    line(g,[[column,top],[column,bottom]],"#e8ebf2",1);
  }
  line(g,[[left,top],[left,bottom],[right,bottom]],"#909aac",1);
  series.forEach((item,index)=>{
    if(!(item.divisor>0))return;
    g.beginPath();g.strokeStyle=index?"#c65b35":accent;
    g.lineWidth=index?1.4:1.7;g.setLineDash(index?[5,3]:[]);
    if(first===last) g.moveTo(x(first),bottom);
    else g.moveTo(left,y(item.counts[first]/item.divisor));
    for(let channel=first;channel<=last;channel++) g.lineTo(x(channel),y(item.counts[channel]/item.divisor));
    g.stroke();
  });
  g.setLineDash([]);g.textAlign="center";g.fillStyle="#101010";
  for(const tick of ticks){
    line(g,[[x(tick.channel),bottom],[x(tick.channel),bottom+4]],"#909aac");
    g.fillText(tick.label,x(tick.channel),bottom+18);
  }
  g.fillText(energy?"能量 / MeV":"道号",(left+right)/2,height-6);
}
