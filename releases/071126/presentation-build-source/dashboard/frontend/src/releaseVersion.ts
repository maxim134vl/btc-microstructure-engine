import { useEffect, useState } from "react";
export type ReleaseManifest = {version?:string;app?:string;channel?:string;real_execution?:string;image_ids?:Record<string,string>};
let pending: Promise<ReleaseManifest|null> | null=null;
function readRelease() { if(!pending) pending=fetch("/release.json",{cache:"no-store"}).then(r=>r.ok?r.json():null).catch(()=>null);return pending; }
export function useReleaseManifest() {const [release,setRelease]=useState<ReleaseManifest|null>(null);useEffect(()=>{let active=true;readRelease().then(v=>{if(active)setRelease(v);});return()=>{active=false;};},[]);return release;}
