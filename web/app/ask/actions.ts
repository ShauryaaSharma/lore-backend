"use server";

import { revalidatePath } from "next/cache";
import { auth } from "@/auth";
import type { Failure } from "@/components/AnswerCard";
import { keyFor } from "@/lib/accounts";
import { lore, LoreError, type WhyResult } from "@/lib/lore";

export type AskResult = { result?: WhyResult; failure?: Failure; message?: string };

export async function ask(account: string, question: string): Promise<AskResult> {
  const session = await auth();
  if (!session?.user?.id) return { message: "Your session expired. Sign in again." };
  question = question.trim();
  if (!question) return { message: "Type a question first." };
  if (question.length > 2000) return { message: "Keep the question under 2,000 characters." };

  const key = await keyFor(session.user.id, account);
  if (!key) return { message: "That GitHub account isn't linked to you." };
  try {
    const result = await lore<WhyResult>("/v1/why", key, { method: "POST", body: JSON.stringify({ question }) });
    revalidatePath("/ask");
    return { result };
  } catch (err) {
    if (err instanceof LoreError && err.status === 429) return { failure: "rate" };
    console.error("ask failed", err);
    return { failure: "error" };
  }
}
