// kit/ — the Tax-Planning-Ops v3 "Daylight & Paper" primitive library.
// Build once, reuse (DESIGN-SPEC §10). Surfaces import from "@/components/kit".
//
// Styling lives in app/globals.css (the ported component layer); these are the
// typed React wrappers that add data, provenance, and interactivity. Charts
// (waterfall, EMR terrain, crossover, entity map, etc.) are built alongside
// their surfaces and added here as they land.

export * from "./tokens";
export * from "./primitives";
export * from "./prov";
export * from "./term";
export * from "./position";
export * from "./cliff";
export * from "./sheet";
export * from "./queue";
export * from "./console";
export * from "./chrome";
