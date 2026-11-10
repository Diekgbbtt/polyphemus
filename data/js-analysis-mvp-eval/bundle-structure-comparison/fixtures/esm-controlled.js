/* Unicode before spans: 😀 é */
import defaultDep from "./dep.js";
import { named } from "./named.js";
import * as namespaceDep from "/absolute/ns.js";
import "./side-effect.js";

export const target = "after-unicode";
export const literalDynamic = () => import("./lazy.js");
const dynamicName = "./runtime-value.js";
export const unresolvedDynamic = () => import(dynamicName);
