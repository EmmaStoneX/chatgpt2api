"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/lib/auth-provider";
import {
  getDefaultRouteForRole,
  type AuthRole,
  type StoredAuthSession,
} from "@/store/auth";

type UseAuthGuardResult = {
  isCheckingAuth: boolean;
  session: StoredAuthSession | null;
};

export function useAuthGuard(allowedRoles?: AuthRole[]): UseAuthGuardResult {
  const router = useRouter();
  const { session, isCheckingAuth } = useAuth();
  const allowedRolesKey = (allowedRoles || []).join(",");

  useEffect(() => {
    if (isCheckingAuth) {
      return;
    }

    const roleList = allowedRolesKey ? (allowedRolesKey.split(",") as AuthRole[]) : [];
    if (!session) {
      router.replace("/login");
      return;
    }

    if (roleList.length > 0 && !roleList.includes(session.role)) {
      router.replace(getDefaultRouteForRole(session.role));
    }
  }, [allowedRolesKey, isCheckingAuth, router, session]);

  return { isCheckingAuth, session };
}

export function useRedirectIfAuthenticated() {
  const router = useRouter();
  const { session, isCheckingAuth } = useAuth();

  useEffect(() => {
    if (!isCheckingAuth && session) {
      router.replace(getDefaultRouteForRole(session.role));
    }
  }, [isCheckingAuth, router, session]);

  return { isCheckingAuth };
}
