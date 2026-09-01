import { Navigate, Outlet, useLocation } from "react-router-dom";
import { LoadingState } from "@/components/page";
import { useAuth } from "@/features/auth/use-auth";

export function RequireAuth() {
  const { user, isLoading } = useAuth();
  const location = useLocation();

  // La prima încărcare, cine este utilizatorul îl spune serverul. Până răspunde,
  // „încă nu știm" nu este același lucru cu „nu e autentificat": o redirectare aici
  // ar arunca la login un operator cu sesiune validă, la fiecare reîncărcare.
  if (isLoading && !user) {
    return <LoadingState label="Se verifică sesiunea…" />;
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
}
