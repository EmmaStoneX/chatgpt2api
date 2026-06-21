"use client";

import { login } from "@/lib/api";
import { clearStoredAuthSession, getStoredAuthSession, setStoredAuthSession, type StoredAuthSession } from "@/store/auth";

type ValidateAuthOptions = {
  clearOnFailure?: boolean;
};

export async function getValidatedAuthSession(options: ValidateAuthOptions = {}): Promise<StoredAuthSession | null> {
  const { clearOnFailure = true } = options;
  const storedSession = await getStoredAuthSession();
  if (!storedSession) {
    return null;
  }

  try {
    const data = await login(storedSession.key);
    const nextSession: StoredAuthSession = {
      key: storedSession.key,
      role: data.role,
      subjectId: data.subject_id,
      name: data.name,
    };
    await setStoredAuthSession(nextSession);
    return nextSession;
  } catch {
    if (clearOnFailure) {
      await clearStoredAuthSession();
    }
    return null;
  }
}
