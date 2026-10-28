import { describe, expect, it } from "vitest";
import { archiveSource } from "./archiveSource";

describe("archiveSource", () => {
  it("names the cloud drive a path is in", () => {
    expect(archiveSource("/Users/a/Library/CloudStorage/GoogleDrive-a@b.fi/My Drive/Archive")).toBe("Google Drive");
    expect(archiveSource("C:\\Users\\a\\Google Drive\\Archive")).toBe("Google Drive");
    expect(archiveSource("/Users/a/Library/CloudStorage/OneDrive-Personal/Archive")).toBe("OneDrive");
    expect(archiveSource("/Users/a/Dropbox/Archive")).toBe("Dropbox");
    expect(archiveSource("/Users/a/Library/Mobile Documents/com~apple~CloudDocs/Archive")).toBe("iCloud Drive");
  });
  it("falls back to the folder's own name, and to nothing without a path", () => {
    expect(archiveSource("/Volumes/Disk/Papers/")).toBe("Papers");
    expect(archiveSource("D:\\Papers")).toBe("Papers");
    expect(archiveSource(null)).toBeNull();
    expect(archiveSource("")).toBeNull();
  });
});
