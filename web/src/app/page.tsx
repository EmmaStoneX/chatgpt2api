"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/lib/auth-provider";
import { getDefaultRouteForRole } from "@/store/auth";

export default function HomePage() {
  const router = useRouter();
  const { session, isCheckingAuth } = useAuth();

  useEffect(() => {
    if (isCheckingAuth) {
      return;
    }
    router.replace(session ? getDefaultRouteForRole(session.role) : "/login");
  }, [isCheckingAuth, router, session]);

  return null;
}
