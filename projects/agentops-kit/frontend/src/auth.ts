import { Amplify } from "aws-amplify";
import { signIn as amplifySignIn, signOut as amplifySignOut, fetchAuthSession, getCurrentUser as amplifyGetCurrentUser } from "aws-amplify/auth";

const POOL_ID = import.meta.env.VITE_COGNITO_USER_POOL_ID || "";
const CLIENT_ID = import.meta.env.VITE_COGNITO_CLIENT_ID || "";
const REGION = import.meta.env.VITE_COGNITO_REGION || "us-east-1";

let configured = false;

export function configureAuth() {
  if (configured) return;
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: POOL_ID,
        userPoolClientId: CLIENT_ID,
        signUpVerificationMethod: "code",
      },
    },
  });
  configured = true;
}

export async function signIn(username: string, password: string): Promise<boolean> {
  configureAuth();
  const result = await amplifySignIn({ username, password });
  return result.isSignedIn;
}

export async function signOut(): Promise<void> {
  await amplifySignOut();
}

export async function getIdToken(): Promise<string | null> {
  try {
    configureAuth();
    const session = await fetchAuthSession();
    return session.tokens?.idToken?.toString() || null;
  } catch {
    return null;
  }
}

export async function isAuthenticated(): Promise<boolean> {
  try {
    configureAuth();
    await amplifyGetCurrentUser();
    return true;
  } catch {
    return false;
  }
}

export interface AuthUser {
  username: string;
  userId: string;
}

export async function getCurrentUser(): Promise<AuthUser | null> {
  try {
    configureAuth();
    const user = await amplifyGetCurrentUser();
    return { username: user.username, userId: user.userId };
  } catch {
    return null;
  }
}
