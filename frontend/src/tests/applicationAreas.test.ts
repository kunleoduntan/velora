import { describe, expect, it } from "vitest";
import { parseHash } from "../router";
import { APPLICATION_AREAS } from "../components/ApplicationAreas";

describe("enterprise application workspaces",()=>{
 it("opens the application area launcher",()=>{expect(parseHash("#/applications").kind).toBe("applications");});
 it("keeps the existing workspace designer route available",()=>{expect(parseHash("#/workspaces").kind).toBe("workspaces");});
 it("provides six distinct operating areas with dashboard metrics",()=>{expect(APPLICATION_AREAS.map(x=>x.id)).toEqual(["finance","assets","payroll","hr","policy","procurement"]);for(const area of APPLICATION_AREAS){expect(area.metrics.length).toBeGreaterThanOrEqual(3);expect(new Set(area.metrics.map(x=>x.doctype)).size).toBe(area.metrics.length);}});
 it("routes curated workspace shortcuts to supported application routes",()=>{
  const routes=["#/financial-centre","#/app/Asset","#/dashboards","#/hr/employee","#/hr/governance","#/app/Purchase Order"];
  expect(routes.map(x=>parseHash(x).kind)).toEqual(["financial-centre","app","dashboards","hr-employee","hr-governance","app"]);
  for(const area of APPLICATION_AREAS)for(const action of area.actions)expect(action.route.startsWith("#/" )).toBe(true);
 });
});
