import type { Metadata } from "next";
import { LoginView } from "@/components/auth/login-view";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return <LoginView />;
}
