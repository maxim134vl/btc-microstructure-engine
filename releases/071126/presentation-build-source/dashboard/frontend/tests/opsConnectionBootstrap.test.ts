/** Targeted transport bootstrap tests. No market/financial runtime. */
import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";
import {readFileSync} from "node:fs";
import {startOpsLiveSession} from "../src/api/client.ts";
import type {OpsSnapshot} from "../src/types/ops.ts";
const fixture=(name:string)=>readFileSync(new URL("./fixtures/connection/"+name,import.meta.url),"utf8");
const snap={snapshot_mode:"TEST_ONLY_CONNECTION",engines:[],ribbon:[]} as OpsSnapshot;
const turn=()=>new Promise(resolve=>setTimeout(resolve,0));
function options(extra:Record<string,unknown>={}){
 return {timeoutMs:25000,pollIntervalMs:4000,maxBackoffMs:15000,offlineAfterFailures:2,
 setTimeoutFn:setTimeout,clearTimeoutFn:clearTimeout,onSnapshot:()=>{},onConnected:()=>{},...extra};
}
test("exact installed bootstrap cannot reach healthy WS while initial HTTP is pending",async()=>{
 const raw=fixture("installed-bootstrap.js");const name=/^function ([^(]+)/.exec(raw)![1];
 const ctx=vm.createContext({AbortController,setTimeout,clearTimeout});
 const baseline=vm.runInContext(raw+`;${name}`,ctx);
 let sockets=0;
 const session=baseline(options({softFetch:()=>new Promise(()=>{}),connectSocket:()=>{sockets++;return{close(){}};}}));
 await turn();assert.equal(sockets,0);assert.equal(session.getPhase(),"RECONNECTING");session.stop();
});
test("patched bootstrap connects WS independently of unresolved HTTP",async()=>{
 let sockets=0,connected=false;let deliver:(s:OpsSnapshot)=>void=()=>{};
 const session=startOpsLiveSession(options({softFetch:()=>new Promise(()=>{}),
  connectSocket:(receive:(s:OpsSnapshot)=>void)=>{sockets++;deliver=receive;return{close(){}};},onConnected:(v:boolean)=>connected=v}) as any);
 assert.equal(sockets,1);deliver(snap);assert.equal(connected,true);assert.equal(session.getPhase(),"LIVE");session.stop();
});
test("initial HTTP failure cannot prevent later valid snapshot handling",async()=>{
 let connected=false;let deliver:(s:OpsSnapshot)=>void=()=>{};
 const session=startOpsLiveSession(options({softFetch:async()=>({ok:false,reason:"network",requestId:1,elapsedMs:1}),
  connectSocket:(receive:(s:OpsSnapshot)=>void)=>{deliver=receive;return{close(){}};},onConnected:(v:boolean)=>connected=v}) as any);
 await turn();assert.equal(connected,false);deliver(snap);assert.equal(connected,true);session.stop();
});
test("late HTTP timeout cannot overwrite a newer WS snapshot",async()=>{
 let finish:(s:any)=>void=()=>{};let deliver:(s:OpsSnapshot)=>void=()=>{};let connected=false;
 const session=startOpsLiveSession(options({softFetch:()=>new Promise(resolve=>finish=resolve),
  connectSocket:(receive:(s:OpsSnapshot)=>void)=>{deliver=receive;return{close(){}};},onConnected:(v:boolean)=>connected=v}) as any);
 deliver(snap);finish({ok:false,reason:"timeout",requestId:1,elapsedMs:25000});await turn();
 assert.equal(connected,true);assert.equal(session.getPhase(),"LIVE");session.stop();
});
test("open socket without a snapshot never grants LIVE",async()=>{
 let signal:(s:boolean)=>void=()=>{};let connected=false;
 const session=startOpsLiveSession(options({softFetch:()=>new Promise(()=>{}),
  connectSocket:(_receive:unknown,status:(s:boolean)=>void)=>{signal=status;return{close(){}};},onConnected:(v:boolean)=>connected=v}) as any);
 signal(true);assert.equal(connected,false);assert.equal(session.getPhase(),"RECONNECTING");session.stop();
});
test("HTTP recovery reuses the same socket and cleanup closes it once",async()=>{
 let sockets=0,closes=0,connected=false;
 const session=startOpsLiveSession(options({softFetch:async()=>({ok:true,snapshot:snap,requestId:1,elapsedMs:1}),
  connectSocket:()=>{sockets++;return{close(){closes++;}};},onConnected:(v:boolean)=>connected=v}) as any);
 await turn();assert.equal(connected,true);assert.equal(sockets,1);session.stop();assert.equal(closes,1);assert.equal(connected,false);
});
test("both transports unavailable remain OFFLINE",async()=>{
 const session=startOpsLiveSession(options({offlineAfterFailures:1,softFetch:async()=>({ok:false,reason:"network",requestId:1,elapsedMs:1}),connectSocket:()=>({close(){}})}) as any);
 await turn();assert.equal(session.getPhase(),"OFFLINE");session.stop();
});
test("actual installed URL helper uses UI same-origin and secure WS on HTTPS",()=>{
 const raw=fixture("installed-base-url.js").replace(/export\{[^}]+\};?/g,"");
 const ctx=vm.createContext({window:{location:{protocol:"http:",host:"127.0.0.1:15173"}}});
 const names=/export\{(\w+) as getApiBase,(\w+) as getWsUrl\}/.exec(fixture("installed-base-url.js"))!;
 const get=vm.runInContext(raw+`;({api:${names[1]},ws:${names[2]}})`,ctx);
 assert.equal(get.api(),"/api/v1");assert.equal(get.ws(),"ws://127.0.0.1:15173/ws/live");
 (ctx as any).window.location={protocol:"https:",host:"ops.example.test"};
 assert.equal(get.ws(),"wss://ops.example.test/ws/live");
});
