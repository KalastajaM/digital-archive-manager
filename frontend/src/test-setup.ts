import "@testing-library/jest-dom/vitest";

// jsdom may lack the modal dialog API; a minimal stand-in keeps <dialog> testable.
if (typeof HTMLDialogElement !== "undefined" && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
}

// jsdom has no layout, so no scrollIntoView; a no-op keeps callers (and spies) working.
if (typeof HTMLElement !== "undefined" && !HTMLElement.prototype.scrollIntoView) {
  HTMLElement.prototype.scrollIntoView = function scrollIntoView() {};
}

// jsdom has no object URLs; previews fetched as blobs get a stand-in "blob:" URL.
if (typeof URL.createObjectURL !== "function") {
  let next = 0;
  URL.createObjectURL = () => `blob:test/${++next}`;
  URL.revokeObjectURL = () => {};
}

// The app names the file manager by platform (fileManager.ts); tests read it as a Mac.
Object.defineProperty(navigator, "platform", { value: "MacIntel", configurable: true });

import { afterEach } from "vitest";
import { resetSignedOut } from "./api/client";

// Forget keys a test pressed without releasing (keyboard.ts tracks held keys), and a 401
// a test provoked (the page would stay on "not signed in").
afterEach(() => {
  window.dispatchEvent(new Event("blur"));
  resetSignedOut();
});
