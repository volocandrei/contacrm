/**
 * Importul de clienți, pe backendul simulat.
 *
 * Backendul simulat este **contractul** (§14): ce se verifică aici trebuie să se
 * comporte identic în `tests/test_client_import.py`. Aici contează mai mult ca
 * oriunde: importul este prima funcție pe care o încearcă un cabinet, iar dacă
 * demonstrația acceptă un fișier pe care serverul real îl refuză — sau invers —
 * omul află asta abia după ce a hotărât să cumpere.
 *
 * Ce se apără, în ordinea gravității:
 *
 * 1. **Previzualizarea nu scrie nimic.**
 * 2. **Nu suprascrie un client existent.**
 * 3. **Același CUI de două ori face un singur client.**
 * 4. **Un rând stricat nu oprește restul.**
 * 5. **Fișierul scris de Excel românesc se citește** — și cel scris cu virgulă.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { createClient, importClients, listClients, mockLogin } from "@/api/mock/store";

const ADMIN = "admin@contacrm.test";
/** Contabilul aleargă după documente; lista de clienți este a administratorului. */
const ACCOUNTANT = "contabil@contacrm.test";

const HEADER = "Denumire;CUI;Nr. reg. com.;Adresă;Status;Persoană de contact;Email;Telefon;WhatsApp";

function file(...rows: string[]): string {
  return [HEADER, ...rows].join("\r\n");
}

/** Un CUI care nu există în setul sintetic, diferit la fiecare apel. */
let counter = 0;
function freshTaxId(): string {
  counter += 1;
  return `9${String(counter).padStart(7, "0")}`;
}

function total(): number {
  return listClients({ page: 1, pageSize: 1 }).total;
}

beforeEach(() => {
  mockLogin(ADMIN);
});

describe("previzualizarea", () => {
  it("nu creează nimic", () => {
    const before = total();

    const plan = importClients(file(`Alfa Import SRL;${freshTaxId()};;;;;;;`), false);

    expect(plan.dryRun).toBe(true);
    expect(plan.created).toBe(1);
    expect(total()).toBe(before);
  });

  it("promite exact ce se întâmplă", () => {
    // Dacă cele două ar putea diferi, primul pas ar fi o minciună liniștitoare.
    const text = file(`Beta Import SRL;${freshTaxId()};;;;;;;`, ";;;;;;;;");
    const before = total();
    const preview = importClients(text, false);

    const applied = importClients(text, true);

    expect(applied.created).toBe(preview.created);
    expect(total()).toBe(before + preview.created);
  });
});

describe("ce nu atinge", () => {
  it("nu suprascrie un client care există deja", () => {
    const taxId = freshTaxId();
    const existing = createClient({ name: "Numele bun SRL", taxId });

    const plan = importClients(file(`Numele vechi din export SRL;RO ${taxId};;;;;;;`), true);

    expect(plan.existing).toBe(1);
    expect(plan.created).toBe(0);
    expect(listClients({ page: 1, pageSize: 200 }).items.find((row) => row.id === existing.id)?.name).toBe(
      "Numele bun SRL",
    );
  });

  it("același CUI de două ori în fișier face un singur client", () => {
    const taxId = freshTaxId();
    const before = total();

    const plan = importClients(
      file(`Gama Import SRL;${taxId};;;;;;;`, `Gama Import S.R.L.;RO ${taxId};;;;;;;`),
      true,
    );

    expect(plan.created).toBe(1);
    expect(plan.duplicates).toBe(1);
    expect(total()).toBe(before + 1);
  });

  it("un rând stricat nu oprește restul", () => {
    // Un fișier de două sute de clienți care cade la al treilea nu se mai încearcă.
    const plan = importClients(
      file(
        `Delta Import SRL;${freshTaxId()};;;;;;;`,
        ";;;;Str. Fără Nume;;;;",
        `Epsilon Import SRL;${freshTaxId()};;;;;;;`,
      ),
      true,
    );

    expect(plan.created).toBe(2);
    expect(plan.invalid).toBe(1);
  });
});

describe("ce citește", () => {
  it("citește și fișierul scris cu virgulă", () => {
    // Exportul făcut de un programator scrie `,`; Excel românesc scrie `;`.
    const plan = importClients(`Denumire,CUI\r\nZeta Import SRL,${freshTaxId()}`, false);

    expect(plan.created).toBe(1);
  });

  it("recunoaște antetul scris altfel", () => {
    // „Nume" și „CIF" în loc de „Denumire" și „CUI": fișierul vine dintr-un
    // export vechi, iar un import care cere cuvintele exacte mută munca înapoi
    // la om — exact munca pe care o economisea.
    const plan = importClients(`Nume;CIF\r\nEta Import SRL;${freshTaxId()}`, false);

    expect(plan.created).toBe(1);
  });

  it("aduce contactul odată cu firma", () => {
    // Fără adresă, clientul nou nu poate primi nici solicitări, nici remindere.
    const taxId = freshTaxId();
    importClients(
      file(`Theta Import SRL;${taxId};;;;Ion Popescu;ion.theta@exemplu.test;0722 333 444;0722 333 444`),
      true,
    );

    const created = listClients({ q: "Theta Import", page: 1, pageSize: 5 }).items[0];
    expect(created).toBeDefined();
  });

  it("semnalează un CUI care nu trece verificarea, dar îl importă", () => {
    // Sunt firme străine, sunt PFA-uri, sunt coduri vechi. Refuzul ar fi
    // însemnat că aplicația știe mai bine decât omul cine sunt clienții lui.
    const plan = importClients(file("Iota Import SRL;RO14399841;;;;;;;"), false);

    expect(plan.rows[0]!.outcome).toBe("NEW");
    expect(plan.rows[0]!.warning).toBeTruthy();
  });
});

describe("cine poate", () => {
  it("contabilul nu poate crea două sute de clienți", () => {
    mockLogin(ACCOUNTANT);

    expect(() => importClients(file("Kappa Import SRL;;;;;;;;"), false)).toThrow();
  });
});
