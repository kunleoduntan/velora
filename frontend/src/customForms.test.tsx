import { describe, expect, it } from "vitest";
import { registerFormComponent, getFormComponent, unregisterFormComponent } from "./customForms";
import type { CustomFormProps } from "./customForms";
import type { ReactNode } from "react";

function DemoForm(_props: CustomFormProps): ReactNode { return null; }

describe("installed-app React custom forms", () => {
  it("registers and resolves a DocType component", () => {
    registerFormComponent("Customer", DemoForm);
    expect(getFormComponent("Customer")).toBe(DemoForm);
    unregisterFormComponent("Customer");
    expect(getFormComponent("Customer")).toBeNull();
  });
});
