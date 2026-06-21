/**
 * Toast notification store + helpers.
 */
"use client";
import { create } from "zustand";

export type ToastVariant = "success" | "error" | "info" | "warn";

export interface Toast {
  id: string;
  title: string;
  description?: string;
  variant: ToastVariant;
  duration?: number;
}

interface ToastState {
  toasts: Toast[];
  push: (t: Omit<Toast, "id">) => string;
  dismiss: (id: string) => void;
  clear: () => void;
}

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  push: (t) => {
    const id = Math.random().toString(36).slice(2, 9);
    set((s) => ({ toasts: [...s.toasts, { id, ...t }] }));
    const duration = t.duration ?? 4000;
    if (duration > 0) setTimeout(() => useToastStore.getState().dismiss(id), duration);
    return id;
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  clear: () => set({ toasts: [] }),
}));

export const toast = {
  success: (title: string, description?: string) =>
    useToastStore.getState().push({ title, description, variant: "success" }),
  error: (title: string, description?: string) =>
    useToastStore.getState().push({ title, description, variant: "error" }),
  info: (title: string, description?: string) =>
    useToastStore.getState().push({ title, description, variant: "info" }),
  warn: (title: string, description?: string) =>
    useToastStore.getState().push({ title, description, variant: "warn" }),
};
