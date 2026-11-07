import { useTheme } from "../../design-system";
export function MarketContextPanel() {const {resolved}=useTheme();return <iframe title="Native Market Context — M15 M30 H1 H4" src={`/market-context/index.html?theme=${resolved}`} className="h-[calc(100vh-52px)] min-h-[700px] w-full border-0" />;}
