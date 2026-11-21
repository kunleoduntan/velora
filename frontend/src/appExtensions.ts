import { api, raw } from "./api";
import type { AppExtensionManifest } from "./api";

/** Load only assets declared by apps installed on the active company. */
export async function loadInstalledAppExtensions(): Promise<() => void> {
  const manifests = await api.appExtensions();
  const urls: string[] = [];
  const nodes: HTMLElement[] = [];
  const loadedApps = new Set<string>();
  try {
    for (const app of manifests) {
      for (const asset of app.frontend_assets ?? []) {
        const path = `/api/app-assets/${encodeURIComponent(app.name)}/${asset.path.split("/").map(encodeURIComponent).join("/")}`;
        const response = await raw("GET", path);
        if (!response.ok) throw new Error(`Could not load ${app.name} frontend asset ${asset.path}: ${response.status}`);
        const url = URL.createObjectURL(await response.blob());
        urls.push(url);
        if (asset.type === "stylesheet") {
          const link = document.createElement("link");
          link.rel = "stylesheet"; link.href = url; link.dataset.veloraApp = app.name;
          document.head.appendChild(link); nodes.push(link);
        } else {
          await new Promise<void>((resolve, reject) => {
            const script = document.createElement("script");
            script.src = url; script.async = false;
            if (asset.path.endsWith(".mjs")) script.type = "module";
            script.dataset.veloraApp = app.name;
            script.onload = () => { nodes.push(script); loadedApps.add(app.name); resolve(); };
            script.onerror = () => { script.remove(); reject(new Error(`Failed to execute ${app.name} asset ${asset.path}`)); };
            document.head.appendChild(script);
          });
        }
      }
    }
  } catch (error) {
    nodes.forEach((node) => node.remove());
    loadedApps.forEach((name) => window.Velora?.unregisterAppComponents?.(name));
    urls.forEach((url) => URL.revokeObjectURL(url));
    throw error;
  }
  return () => {
    nodes.forEach((node) => node.remove());
    manifests.forEach((app) => window.Velora?.unregisterAppComponents?.(app.name));
    urls.forEach((url) => URL.revokeObjectURL(url));
  };
}
