/**
 * Formularele prin care se adaugă și se modifică un client și contactele lui.
 *
 * **De ce apar abia acum.** CRM-ul a fost de la început numai de citire — drumul
 * de scriere al aplicației sunt documentele. Auditul de producție a arătat
 * consecința: un cabinet nou nu putea adăuga niciun client, deci nu putea lega
 * niciun dosar din OneDrive și niciun email nu putea fi atribuit.
 *
 * **Nu există ștergere.** Un client cu documente este istorie contabilă; ce se
 * cere de fapt este „nu mai lucrez cu el", iar asta este statusul `INACTIV`.
 * Un buton „Șterge" ar fi arătat ca soluția evidentă exact în momentul greșit.
 *
 * Validarea care contează stă pe server: CUI-ul unic pe forma normalizată și
 * adresa de email unică între clienți. Aici nu există o a doua copie a lor —
 * formularul arată ce răspunde serverul.
 */
import { useState } from "react";
import { CircleAlert, LoaderCircle } from "lucide-react";
import { useSaveClient, useSaveContact, useUsers } from "@/api/hooks";
import type { ClientInput, ContactInput } from "@/api/endpoints";
import { SelectFilter, TextField } from "@/components/form-controls";
import { Panel } from "@/components/page";
import { ApiError } from "@/api/types";
import { CLIENT_STATUS, type Client, type ClientStatus, type Contact } from "@/types/domain";

const STATUS_LABEL: Record<ClientStatus, string> = {
  ACTIVE: "Activ",
  INACTIVE: "Inactiv",
  PROSPECT: "Prospect",
  SUSPENDED: "Suspendat",
};

/** Mesajul serverului, plus câmpurile pe care le-a respins. */
function FormError({ error }: { error: unknown }) {
  if (!error) return null;
  const message =
    error instanceof ApiError ? error.message : "Nu am putut salva. Încearcă din nou.";
  return (
    <p
      role="alert"
      className="mb-3 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200"
    >
      <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <span>{message}</span>
    </p>
  );
}

function Actions({
  saving,
  onCancel,
  label,
}: {
  saving: boolean;
  onCancel: () => void;
  label: string;
}) {
  return (
    <div className="mt-4 flex items-center gap-2">
      <button
        type="submit"
        disabled={saving}
        className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {saving && <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />}
        {label}
      </button>
      <button
        type="button"
        onClick={onCancel}
        className="rounded-lg px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800"
      >
        Renunță
      </button>
    </div>
  );
}

/* ─── Client ───────────────────────────────────────────────────────────────── */

export function ClientForm({
  client,
  onDone,
  onCancel,
}: {
  /** Absent = client nou. */
  client?: Client;
  onDone: (saved: Client) => void;
  onCancel: () => void;
}) {
  const save = useSaveClient();
  const { data: users } = useUsers();
  const [values, setValues] = useState<ClientInput>({
    name: client?.name ?? "",
    taxId: client?.taxId ?? "",
    registrationNumber: client?.registrationNumber ?? "",
    address: client?.address ?? "",
    status: client?.status ?? "ACTIVE",
    assignedAccountantId: client?.assignedAccountantId ?? null,
  });

  function set<K extends keyof ClientInput>(key: K, value: ClientInput[K]) {
    setValues((current) => ({ ...current, [key]: value }));
  }

  return (
    <Panel title={client ? "Modifică clientul" : "Client nou"}>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate({ id: client?.id, input: values }, { onSuccess: onDone });
        }}
      >
        <FormError error={save.error} />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <TextField
            id="client-name"
            label="Denumire"
            value={values.name ?? ""}
            onChange={(value) => set("name", value)}
            placeholder="Exemplu Contabil SRL"
            className="sm:col-span-2"
          />
          <TextField
            id="client-taxId"
            label="CUI"
            value={values.taxId ?? ""}
            onChange={(value) => set("taxId", value)}
            placeholder="RO12345678"
            hint={
              <span className="font-normal text-gray-400">după el se identifică facturile</span>
            }
          />
          <TextField
            id="client-registrationNumber"
            label="Nr. registrul comerțului"
            value={values.registrationNumber ?? ""}
            onChange={(value) => set("registrationNumber", value)}
            placeholder="J40/1234/2020"
          />
          <TextField
            id="client-address"
            label="Adresă"
            value={values.address ?? ""}
            onChange={(value) => set("address", value)}
            className="sm:col-span-2"
          />
          <SelectFilter
            label="Status"
            showLabel
            includeAll={false}
            value={values.status ?? "ACTIVE"}
            onChange={(value) => set("status", value as ClientStatus)}
            options={CLIENT_STATUS.map((status) => ({
              value: status,
              label: STATUS_LABEL[status],
            }))}
          />
          <SelectFilter
            label="Contabil atribuit"
            showLabel
            allLabel="Neatribuit"
            value={values.assignedAccountantId ?? ""}
            onChange={(value) => set("assignedAccountantId", value || null)}
            options={(users ?? []).map((user) => ({ value: user.id, label: user.fullName }))}
          />
        </div>

        <Actions
          saving={save.isPending}
          onCancel={onCancel}
          label={client ? "Salvează" : "Adaugă clientul"}
        />
      </form>
    </Panel>
  );
}

/* ─── Contact ──────────────────────────────────────────────────────────────── */

export function ContactForm({
  clientId,
  contact,
  onDone,
  onCancel,
}: {
  clientId: string;
  contact?: Contact;
  onDone: () => void;
  onCancel: () => void;
}) {
  const save = useSaveContact(clientId);
  const [values, setValues] = useState<ContactInput>({
    fullName: contact?.fullName ?? "",
    role: contact?.role ?? "",
    email: contact?.email ?? "",
    phone: contact?.phone ?? "",
    whatsappNumber: contact?.whatsappNumber ?? "",
    isPrimary: contact?.isPrimary ?? false,
    isActive: contact?.isActive ?? true,
  });

  function set<K extends keyof ContactInput>(key: K, value: ContactInput[K]) {
    setValues((current) => ({ ...current, [key]: value }));
  }

  return (
    <Panel title={contact ? "Modifică contactul" : "Contact nou"}>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate({ id: contact?.id, input: values }, { onSuccess: onDone });
        }}
      >
        <FormError error={save.error} />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <TextField
            id="contact-fullName"
            label="Nume"
            value={values.fullName ?? ""}
            onChange={(value) => set("fullName", value)}
          />
          <TextField
            id="contact-role"
            label="Rol"
            value={values.role ?? ""}
            onChange={(value) => set("role", value)}
            placeholder="Administrator"
          />
          <TextField
            id="contact-email"
            label="Email"
            type="email"
            value={values.email ?? ""}
            onChange={(value) => set("email", value)}
            hint={
              <span className="font-normal text-gray-400">
                după el ajung documentele trimise pe email
              </span>
            }
            className="sm:col-span-2"
          />
          <TextField
            id="contact-phone"
            label="Telefon"
            value={values.phone ?? ""}
            onChange={(value) => set("phone", value)}
          />
          <TextField
            id="contact-whatsappNumber"
            label="WhatsApp"
            value={values.whatsappNumber ?? ""}
            onChange={(value) => set("whatsappNumber", value)}
          />
        </div>

        <div className="mt-4 flex flex-wrap gap-5">
          <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
            <input
              type="checkbox"
              checked={values.isPrimary ?? false}
              onChange={(event) => set("isPrimary", event.target.checked)}
              className="h-4 w-4 rounded border-gray-300"
            />
            Contact principal
          </label>
          <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
            <input
              type="checkbox"
              checked={values.isActive ?? true}
              onChange={(event) => set("isActive", event.target.checked)}
              className="h-4 w-4 rounded border-gray-300"
            />
            Activ
          </label>
        </div>

        <Actions
          saving={save.isPending}
          onCancel={onCancel}
          label={contact ? "Salvează" : "Adaugă contactul"}
        />
      </form>
    </Panel>
  );
}
