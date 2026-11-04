import { GuestGuard } from "@/components/auth/auth-guard";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return <GuestGuard>{children}</GuestGuard>;
}
