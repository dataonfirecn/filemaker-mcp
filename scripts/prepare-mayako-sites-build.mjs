import { access, cp, mkdir, rm } from "node:fs/promises";
import { constants } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const frontendBuild = resolve(repositoryRoot, "frontend", "dist");
const outputRoot = resolve(repositoryRoot, "dist");
const clientOutput = resolve(outputRoot, "client");
const serverOutput = resolve(outputRoot, "server");

const customerHtml = resolve(frontendBuild, "customer.html");
const frontendAssets = resolve(frontendBuild, "assets");
const workerSource = resolve(repositoryRoot, "deploy", "sites", "mayako-worker.js");

await Promise.all([
  access(customerHtml, constants.R_OK),
  access(frontendAssets, constants.R_OK),
  access(workerSource, constants.R_OK)
]);

await rm(outputRoot, { recursive: true, force: true });
await Promise.all([
  mkdir(clientOutput, { recursive: true }),
  mkdir(serverOutput, { recursive: true })
]);

await Promise.all([
  cp(customerHtml, resolve(clientOutput, "customer.html")),
  cp(frontendAssets, resolve(clientOutput, "assets"), { recursive: true }),
  cp(workerSource, resolve(serverOutput, "index.js"))
]);

console.log("Prepared Mayako Sites build in dist/");
