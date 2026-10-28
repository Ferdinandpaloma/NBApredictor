// Firebase sign-in (Google, email/password) and each user's saved bets.
// Config comes from VITE_FIREBASE_* in .env; without it the site still works,
// it just shows that sign-in isn't set up.
import { initializeApp } from "firebase/app";
import {
  GoogleAuthProvider, createUserWithEmailAndPassword, getAuth, getRedirectResult,
  onAuthStateChanged, sendPasswordResetEmail, signInWithEmailAndPassword,
  signInWithPopup, signInWithRedirect, signOut as fbSignOut, updateProfile,
} from "firebase/auth";
import {
  addDoc, collection, deleteDoc, doc, getDocs, getFirestore, orderBy, query, serverTimestamp,
} from "firebase/firestore";

const env = import.meta.env;
const config = {
  apiKey: env.VITE_FIREBASE_API_KEY,
  authDomain: env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: env.VITE_FIREBASE_APP_ID,
};
export const configured = Boolean(config.apiKey && config.authDomain && config.projectId && config.appId);

let auth, db;
if (configured) {
  const app = initializeApp(config);
  auth = getAuth(app);
  db = getFirestore(app);
  getRedirectResult(auth).catch(() => {});  // finishes a Google redirect sign-in, if one is in flight
}

export function onUser(cb) {
  if (!configured) { cb(null); return () => {}; }
  return onAuthStateChanged(auth, cb);
}

export async function signInGoogle() {
  const provider = new GoogleAuthProvider();
  try {
    await signInWithPopup(auth, provider);
  } catch (e) {
    // Popups can be blocked, e.g. in an iPhone home-screen app; fall back to a full-page redirect.
    if (e.code === "auth/popup-blocked" || e.code === "auth/operation-not-supported-in-this-environment") {
      return signInWithRedirect(auth, provider);
    }
    throw e;
  }
}

export const signInEmail = (email, password) => signInWithEmailAndPassword(auth, email, password);

export async function signUpEmail(email, password, name) {
  const cred = await createUserWithEmailAndPassword(auth, email, password);
  if (name) await updateProfile(cred.user, { displayName: name });
  return cred;
}

export const resetPassword = email => sendPasswordResetEmail(auth, email);
export const signOut = () => fbSignOut(auth);

// Bets live at users/{uid}/bets/{id}; firestore.rules lets each user see only their own.
const bets = () => collection(db, "users", auth.currentUser.uid, "bets");
export async function listBets() {
  const snap = await getDocs(query(bets(), orderBy("createdAt", "desc")));
  return snap.docs.map(d => ({ id: d.id, ...d.data() }));
}
export const saveBet = bet => addDoc(bets(), { ...bet, createdAt: serverTimestamp() });
export const deleteBet = id => deleteDoc(doc(db, "users", auth.currentUser.uid, "bets", id));

const MESSAGES = {
  "auth/invalid-email": "That email address doesn't look right.",
  "auth/missing-password": "Enter a password.",
  "auth/weak-password": "Use at least 6 characters for the password.",
  "auth/email-already-in-use": "There's already an account with that email. Sign in instead.",
  "auth/invalid-credential": "Wrong email or password.",
  "auth/user-not-found": "No account with that email.",
  "auth/wrong-password": "Wrong email or password.",
  "auth/too-many-requests": "Too many tries. Wait a minute and try again.",
  "auth/network-request-failed": "Network problem. Check your connection.",
  "auth/unauthorized-domain": "This website isn't on the Firebase authorized-domains list yet.",
  "auth/operation-not-allowed": "That sign-in method isn't turned on in Firebase yet.",
  "permission-denied": "Firestore blocked that. Check the security rules are published.",
  "auth/api-key-not-valid.-please-pass-a-valid-api-key.": "The Firebase config in .env is wrong (bad API key).",
};
export function errorMessage(e) {
  if (e?.code === "auth/popup-closed-by-user" || e?.code === "auth/cancelled-popup-request") return "";
  return MESSAGES[e?.code] || e?.message || "Something went wrong.";
}
