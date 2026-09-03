/**
 * Setările pe backend-ul simulat (§16, §73).
 *
 * Paritatea cheilor cu serverul real este verificată în Python
 * (`tests/test_contract.py`), unde se pot citi amândouă implementările. Aici
 * rămâne ce se poate verifica doar de partea asta: că ecranul este închis pentru
 * cine nu administrează, și că valorile spun adevărul despre demonstrație.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { ApiError } from "@/api/types";
import { listSettings, mockLogin } from "@/api/mock/store";

const ADMIN = "admin@contacrm.test";
/** REVIEWER are `documents:approve`, dar nu `admin:settings`. */
const REVIEWER = "verificator@contacrm.test";

beforeEach(() => {
  mockLogin(ADMIN);
});

describe("acces", () => {
  it("cere `admin:settings`, nu doar o sesiune", () => {
    mockLogin(REVIEWER);
    expect(() => listSettings()).toThrow(ApiError);
  });
});

describe("ce se publică", () => {
  it("nu conține nimic care să semene a secret sau a adresă", () => {
    // §73 — aceeași regulă ca în backend, verificată și aici pentru că lista de
    // aici este scrisă de mână și ar putea aluneca independent.
    for (const entry of listSettings()) {
      expect(entry.value).not.toContain("://");
      expect(entry.value).not.toContain("@");
    }
  });

  it("nu publică nicio cale de pe disc", () => {
    const keys = listSettings().map((entry) => entry.key);
    expect(keys).not.toContain("STORAGE_PATH");
    expect(keys).not.toContain("ARCHIVE_ROOT");
    expect(keys).not.toContain("DATABASE_URL");
    expect(keys).not.toContain("SECRET_KEY");
  });

  it("spune adevărul despre demonstrație: nimic nu pleacă de pe mașina asta", () => {
    // R2. Backend-ul simulat chiar nu are provider de OCR sau AI; dacă ar copia
    // valorile de producție, ecranul ar minți la fel ca înainte, cu alt text.
    const values = Object.fromEntries(listSettings().map((e) => [e.key, e.value]));
    expect(values.OCR_PROVIDER).toBe("mock");
    expect(values.AI_PROVIDER).toBe("mock");
    expect(values.NOTIFICATIONS_ENABLED).toBe("false");
  });

  it("valorile logice sunt șiruri stabile", () => {
    const booleans = ["AUTO_APPROVE_ENABLED", "NOTIFICATIONS_ENABLED", "RETENTION_ENABLED"];
    const values = Object.fromEntries(listSettings().map((e) => [e.key, e.value]));
    for (const key of booleans) {
      expect(["true", "false"]).toContain(values[key]);
    }
  });

  it("fiecare cheie apare o singură dată", () => {
    const keys = listSettings().map((entry) => entry.key);
    expect(keys.length).toBe(new Set(keys).size);
  });
});
