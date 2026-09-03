/**
 * Luna „acum", pentru filtrele care au nevoie de o valoare implicită.
 *
 * În demonstrație, „acum" este momentul setului sintetic: datele se opresc în
 * august 2026, iar un filtru pornit pe luna calendaristică ar deschide un ecran
 * gol și ar lăsa impresia că aplicația este stricată. Pe API-ul real, „acum"
 * este ceasul real.
 *
 * Aceasta **nu** este luna pe care o descriu cifrele din panoul principal: aceea
 * o dă serverul, derivată din date (`latest_active_month`), și vine în
 * `DashboardData.referenceMonth`. Un filtru alege de unde să pornească; un titlu
 * afirmă ceva despre niște numere. Confuzia dintre ele a fost exact defectul.
 */
import { apiMode } from "@/api/client";
import { MOCK_NOW } from "@/api/mock/seed";

export function currentMonth(): string {
  if (apiMode() === "mock") return MOCK_NOW.slice(0, 7);

  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}
