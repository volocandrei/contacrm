/**
 * Integrarea OneDrive pe backend-ul simulat (M9).
 *
 * Paritatea cu serverul real este verificată în Python. Aici rămâne ce se poate
 * verifica doar de partea asta: că ecranul este închis pentru cine nu
 * administrează, și că demonstrația chiar arată ce a cerut cabinetul —
 * documentele apar singure, la clientul dosarului.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { ApiError } from "@/api/types";
import {
  browseDrive,
  connectDrive,
  disconnectDrive,
  getDriveStatus,
  listDocuments,
  mockLogin,
  syncDrive,
  trackDriveFolder,
  untrackDriveFolder,
  updateDriveFolder,
} from "@/api/mock/store";

const ADMIN = "admin@contacrm.test";
/** ACCOUNTANT are `documents:approve`, dar nu `admin:settings`. */
const ACCOUNTANT = "contabil@contacrm.test";

beforeEach(() => {
  mockLogin(ADMIN);
  // Starea drive-ului trăiește în modul: fiecare test pornește deconectat.
  if (getDriveStatus().connected) disconnectDrive();
});

describe("acces", () => {
  it("cere `admin:settings`, nu doar o sesiune", () => {
    // Cine poate conecta un OneDrive poate citi documentele tuturor clienților.
    mockLogin(ACCOUNTANT);
    expect(() => getDriveStatus()).toThrow(ApiError);
  });
});

describe("conectarea", () => {
  it("pornește deconectat", () => {
    const status = getDriveStatus();
    expect(status.connected).toBe(false);
    expect(status.folders).toEqual([]);
  });

  it("conectarea arată contul", () => {
    const status = connectDrive();
    expect(status.connected).toBe(true);
    expect(status.accountEmail).toContain("@");
  });

  it("deconectarea nu lasă dosare în urmă", () => {
    connectDrive();
    trackDriveFolder({ driveId: "drive-demo", itemId: "d-cl-1", path: "/Clienți/ALFA CONTA SRL" });

    disconnectDrive();

    const status = getDriveStatus();
    expect(status.connected).toBe(false);
    expect(status.folders).toEqual([]);
  });

  it("răsfoirea cere o conexiune", () => {
    expect(() => browseDrive()).toThrow(ApiError);
  });
});

describe("dosarele", () => {
  beforeEach(() => {
    connectDrive();
  });

  it("răsfoirea arată dosarele, nu fișiere", () => {
    const items = browseDrive();
    expect(items.length).toBeGreaterThan(0);
    expect(items.every((item) => typeof item.itemId === "string")).toBe(true);
  });

  it("un dosar deja urmărit este marcat", () => {
    const [first] = browseDrive("d-clienti");
    trackDriveFolder({ driveId: first!.driveId, itemId: first!.itemId, path: first!.path });

    const after = browseDrive("d-clienti");
    expect(after.find((item) => item.itemId === first!.itemId)?.isTracked).toBe(true);
  });

  it("același dosar nu se urmărește de două ori", () => {
    const payload = { driveId: "drive-demo", itemId: "d-cl-1", path: "/Clienți/ALFA CONTA SRL" };
    trackDriveFolder(payload);

    expect(() => trackDriveFolder(payload)).toThrow(ApiError);
  });

  it("un dosar poate fi dezlegat de client", () => {
    const folder = trackDriveFolder({
      driveId: "drive-demo",
      itemId: "d-cl-1",
      path: "/Clienți/ALFA CONTA SRL",
    });

    const updated = updateDriveFolder(folder.id, { clientId: null });

    expect(updated.clientId).toBeNull();
    expect(updated.clientName).toBeNull();
  });

  it("un dosar poate fi scos de sub urmărire", () => {
    const folder = trackDriveFolder({ driveId: "drive-demo", itemId: "d-x", path: "/X" });
    untrackDriveFolder(folder.id);

    expect(getDriveStatus().folders).toEqual([]);
  });
});

describe("sincronizarea", () => {
  it("cere o conexiune", () => {
    expect(() => syncDrive()).toThrow(ApiError);
  });

  it("nu aduce nimic fără dosare urmărite", () => {
    connectDrive();
    expect(syncDrive().ingested).toBe(0);
  });

  it("documentele apar singure, la clientul dosarului", () => {
    // Exact ce a cerut cabinetul: nimeni nu descarcă și nimeni nu atribuie.
    connectDrive();
    const [first] = browseDrive("d-clienti");
    const folder = trackDriveFolder({
      driveId: first!.driveId,
      itemId: first!.itemId,
      path: first!.path,
    });
    const before = listDocuments({ pageSize: 1 }).total;

    const result = syncDrive();

    expect(result.ingested).toBe(1);
    expect(listDocuments({ pageSize: 1 }).total).toBe(before + 1);

    const fromDrive = listDocuments({ source: "ONEDRIVE", pageSize: 50 }).items;
    expect(fromDrive.some((doc) => doc.clientId === folder.clientId)).toBe(true);
  });

  it("ține minte când a sincronizat ultima dată", () => {
    connectDrive();
    trackDriveFolder({ driveId: "drive-demo", itemId: "d-cl-1", path: "/Clienți/ALFA CONTA SRL" });

    syncDrive();

    const status = getDriveStatus();
    expect(status.lastSyncAt).not.toBeNull();
    expect(status.folders[0]!.lastSyncedAt).not.toBeNull();
    expect(status.folders[0]!.filesIngested).toBe(1);
  });
});
