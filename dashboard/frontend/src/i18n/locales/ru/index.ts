import { ruCommon } from "./common";
import { ruNav } from "./nav";
import { ruShell } from "./shell";
import { ruStatus } from "./status";
import { ruOps } from "./ops";
import { ruValidation } from "./validation";
import { ruMarketState } from "./marketState";
import {
  ruVisualCognition,
  ruMarketIntelligence,
  ruRuntimeActivity,
  ruStage1,
  ruCognitiveReview,
} from "./misc";

export const ru = {
  common: ruCommon,
  nav: ruNav,
  shell: ruShell,
  status: ruStatus,
  ops: ruOps,
  validation: ruValidation,
  visualCognition: ruVisualCognition,
  marketIntelligence: ruMarketIntelligence,
  runtimeActivity: ruRuntimeActivity,
  stage1: ruStage1,
  cognitiveReview: ruCognitiveReview,
  marketState: ruMarketState,
};
