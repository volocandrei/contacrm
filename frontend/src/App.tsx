import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/layout/app-shell";
import { AuditLogPage, RolesPage, SettingsPage, UsersPage } from "@/features/admin/admin-pages";
import { AnafPage } from "@/features/admin/anaf-page";
import { DrivePage } from "@/features/admin/drive-page";
import { LoginPage } from "@/features/auth/login-page";
import { RequireAuth } from "@/features/auth/require-auth";
import { ClientDetailPage } from "@/features/clients/client-detail-page";
import { ContactsPage } from "@/features/clients/contacts-page";
import { ClientsPage } from "@/features/clients/clients-page";
import {
  MessagesPage,
  RemindersPage,
  TemplatesPage,
} from "@/features/communication/communication-pages";
import { DashboardPage } from "@/features/dashboard/dashboard-page";
import { DocumentsPage } from "@/features/documents/documents-page";
import { ReviewPage, ReviewQueuePage } from "@/features/documents/review-page";
import { MissingDocumentsPage, PeriodsPage } from "@/features/periods/periods-page";
import { ReportsPage } from "@/features/reports/reports-page";
import { TasksPage } from "@/features/tasks/tasks-page";

function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route index element={<DashboardPage />} />

          {/* CRM */}
          <Route path="/crm/clienti" element={<ClientsPage />} />
          <Route path="/crm/clienti/:id" element={<ClientDetailPage />} />
          <Route path="/crm/contacte" element={<ContactsPage />} />
          <Route path="/crm/sarcini" element={<TasksPage />} />

          {/* Documente */}
          <Route
            path="/documente/inbox"
            element={
              <DocumentsPage
                preset="inbox"
                title="Inbox documente"
                description="Tot ce a sosit și nu a fost încă arhivat"
              />
            }
          />
          <Route
            path="/documente/procesare"
            element={
              <DocumentsPage
                preset="processing"
                title="În procesare"
                description="Documente aflate în pipeline-ul OCR/AI"
              />
            }
          />
          <Route
            path="/documente/verificare"
            element={
              <DocumentsPage
                preset="review"
                title="Verificare"
                description="Documente care necesită confirmarea unui operator"
              />
            }
          />
          <Route
            path="/documente/neatribuite"
            element={
              <DocumentsPage
                preset="unmatched"
                title="Neatribuite"
                description="Documente sosite fără client identificat — au nevoie de cineva care cunoaște firmele"
              />
            }
          />
          <Route path="/documente/verificare/:id" element={<ReviewPage />} />
          <Route path="/documente/verificare/coada" element={<ReviewQueuePage />} />
          <Route
            path="/documente/arhiva"
            element={
              <DocumentsPage
                preset="archive"
                title="Arhivă"
                description="Documente aprobate și arhivate, cu denumire standardizată"
              />
            }
          />

          {/* Contabilitate */}
          <Route path="/contabilitate/perioade" element={<PeriodsPage />} />
          <Route path="/contabilitate/lipsa" element={<MissingDocumentsPage />} />

          {/* Comunicare */}
          <Route path="/comunicare/mesaje" element={<MessagesPage />} />
          <Route path="/comunicare/sabloane" element={<TemplatesPage />} />
          <Route path="/comunicare/remindere" element={<RemindersPage />} />

          {/* Rapoarte */}
          <Route path="/rapoarte" element={<ReportsPage />} />

          {/* Administrare */}
          <Route path="/administrare/utilizatori" element={<UsersPage />} />
          <Route path="/administrare/roluri" element={<RolesPage />} />
          <Route path="/administrare/setari" element={<SettingsPage />} />
          <Route path="/administrare/surse" element={<DrivePage />} />
          <Route path="/administrare/e-factura" element={<AnafPage />} />
          <Route path="/administrare/audit" element={<AuditLogPage />} />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Route>
    </Routes>
  );
}

export default App;
