/**
 * Agenda cabinetului.
 *
 * **Ce era înainte.** Ecranul cerea lista de clienți (200 deodată) și apoi, din
 * fiecare card, contactele acelui client: `GET /clients/{id}/contacts` de
 * treizeci de ori pentru treizeci de clienți, pornite simultan la deschidere.
 * Clienții fără contacte nu randau nimic, deci pagina putea arăta aproape goală
 * în timp ce bombarda serverul. Și nu se putea căuta: dacă știai numele
 * persoanei, dar nu firma, nu aveai ce face cu ea.
 *
 * **Ce este acum.** O singură cerere, căutare care acoperă și persoana și firma,
 * și — partea care contează la o agendă — datele de contact sunt **acționabile**:
 * un click sună, scrie sau deschide WhatsApp. Un număr de telefon pe care
 * trebuie să-l copiezi cu ochiul nu este o agendă, este o listă.
 */
import { Link } from "react-router-dom";
import { Building2, Mail, MessageCircle, Phone, Star } from "lucide-react";
import { useContacts } from "@/api/hooks";
import { Pagination, SearchInput } from "@/components/form-controls";
import { PageHeader, Panel, QueryBoundary } from "@/components/page";
import { useFilterParams } from "@/hooks/use-filter-params";
import { avatarTone, initials } from "@/lib/avatar";
import { iconChip, mutedText, pillClass } from "@/lib/ui";
import { cn } from "@/lib/utils";
import type { ContactListItem } from "@/types/domain";

const PAGE_SIZE = 30;

export function ContactsPage() {
  const { values, setValue } = useFilterParams({ q: "", page: "1" });
  const { data, isLoading, error } = useContacts({
    q: values.q,
    page: Number(values.page) || 1,
    pageSize: PAGE_SIZE,
  });

  return (
    <div>
      <PageHeader
        title="Contacte"
        description="Cu cine vorbești la fiecare firmă"
        actions={
          data && (
            <span className={pillClass("blue")}>
              {data.total} {data.total === 1 ? "persoană" : "persoane"}
            </span>
          )
        }
      />

      <SearchInput
        label="Caută în agendă"
        value={values.q}
        // `useFilterParams` readuce singur paginarea la prima pagină: altfel
        // căutarea ar părea fără rezultate doar pentru că pagina 3 nu mai există.
        onChange={(value) => setValue("q", value)}
        placeholder="Nume, firmă, email, telefon…"
        className="mb-4 w-full sm:w-96"
      />

      <Panel bodyClassName="p-0">
        <QueryBoundary
          isLoading={isLoading}
          error={error}
          isEmpty={data?.items.length === 0}
          emptyTitle={values.q ? `Nimic pentru „${values.q}"` : "Nicio persoană de contact"}
          emptyDescription="Contactele se adaugă din fișa clientului."
        >
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {data?.items.map((contact) => <ContactRow key={contact.id} contact={contact} />)}
          </ul>
          {data && (
            <Pagination
              page={data.page}
              totalPages={data.totalPages}
              total={data.total}
              pageSize={data.pageSize}
              onPageChange={(page) => setValue("page", String(page))}
            />
          )}
        </QueryBoundary>
      </Panel>
    </div>
  );
}

function ContactRow({ contact }: { contact: ContactListItem }) {
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/40">
      <span
        className={cn(
          "grid h-10 w-10 shrink-0 place-content-center rounded-xl text-xs font-semibold",
          iconChip[avatarTone(contact.fullName)],
        )}
        aria-hidden="true"
      >
        {initials(contact.fullName)}
      </span>

      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-slate-900 dark:text-slate-100">
          {contact.fullName}
          {/* Contactul principal este cel pe care îl suni întâi. Steaua spune
              asta fără să ocupe un rând de text. */}
          {contact.isPrimary && (
            <span className={pillClass("amber")} title="Contact principal">
              <Star className="h-3 w-3" aria-hidden="true" />
              principal
            </span>
          )}
          {contact.role && <span className={cn("text-xs font-normal", mutedText)}>{contact.role}</span>}
        </p>
        <Link
          to={`/crm/clienti/${contact.clientId}`}
          className={cn("flex items-center gap-1 text-xs hover:underline", mutedText)}
        >
          <Building2 className="h-3 w-3" aria-hidden="true" />
          {contact.clientName}
        </Link>
      </div>

      <div className="flex flex-wrap items-center gap-1">
        {contact.email && (
          <Action href={`mailto:${contact.email}`} Icon={Mail} label="Scrie email">
            {contact.email}
          </Action>
        )}
        {contact.phone && (
          <Action href={`tel:${contact.phone.replace(/\s/g, "")}`} Icon={Phone} label="Sună">
            {contact.phone}
          </Action>
        )}
        {contact.whatsappNumber && (
          <Action
            href={`https://wa.me/${contact.whatsappNumber.replace(/\D/g, "")}`}
            Icon={MessageCircle}
            label="Deschide WhatsApp"
          >
            WhatsApp
          </Action>
        )}
      </div>
    </li>
  );
}

/** Un mijloc de a lua legătura, care chiar o ia. */
function Action({
  href,
  Icon,
  label,
  children,
}: {
  href: string;
  Icon: typeof Mail;
  label: string;
  children: React.ReactNode;
}) {
  const external = href.startsWith("http");
  return (
    <a
      href={href}
      title={label}
      {...(external ? { target: "_blank", rel: "noreferrer noopener" } : {})}
      className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1 text-xs text-slate-600 transition-colors hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 dark:border-slate-800 dark:text-slate-400 dark:hover:border-blue-900 dark:hover:bg-blue-950/40 dark:hover:text-blue-300"
    >
      <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span className="max-w-48 truncate">{children}</span>
    </a>
  );
}
