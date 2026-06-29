"use client";

import localforage from "localforage";

import type { ImageModel } from "@/lib/api";
import { httpRequest, request } from "@/lib/request";

export type ImageConversationMode = "generate" | "edit";

export type StoredReferenceImage = {
  name: string;
  type: string;
  dataUrl?: string;
  url?: string;
  rel?: string;
  expiresAt?: string;
  expired?: boolean;
};

export type StoredImage = {
  id: string;
  taskId?: string;
  status?: "loading" | "success" | "error";
  taskStatus?: "queued" | "running";
  progress?: string;
  b64_json?: string;
  url?: string;
  rel?: string;
  revised_prompt?: string;
  error?: string;
  expiresAt?: string;
  expired?: boolean;
  startTime?: number;
  elapsedSecs?: number;
  elapsedUpdatedAt?: number;
  durationMs?: number;
};

export type ImageTurnStatus = "queued" | "generating" | "success" | "error";

export type ImageTurn = {
  id: string;
  prompt: string;
  model: ImageModel;
  mode: ImageConversationMode;
  referenceImages: StoredReferenceImage[];
  count: number;
  size: string;
  ratio: string;
  tier: string;
  quality: string;
  images: StoredImage[];
  createdAt: string;
  status: ImageTurnStatus;
  error?: string;
  promptDeleted?: boolean;
  resultsDeleted?: boolean;
};

export type ImageConversation = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  turns: ImageTurn[];
};

export type ImageConversationStats = {
  queued: number;
  running: number;
};

const imageConversationStorage = localforage.createInstance({
  name: "chatgpt2api",
  storeName: "image_conversations",
});

const SERVER_IMAGE_CONVERSATIONS_CACHE_KEY = "server_items";
let imageConversationWriteQueue: Promise<void> = Promise.resolve();

function normalizeStoredImage(image: StoredImage): StoredImage {
  const normalizedUrl = typeof image.url === "string" && image.url ? image.url : undefined;
  const normalized = {
    ...image,
    taskId: typeof image.taskId === "string" && image.taskId ? image.taskId : undefined,
    taskStatus: image.taskStatus === "queued" || image.taskStatus === "running" ? image.taskStatus : undefined,
    url: normalizedUrl,
    rel: typeof image.rel === "string" && image.rel ? image.rel : undefined,
    revised_prompt: typeof image.revised_prompt === "string" ? image.revised_prompt : undefined,
    expiresAt: typeof image.expiresAt === "string" ? image.expiresAt : undefined,
    expired: image.expired === true,
    startTime: typeof image.startTime === "number" ? image.startTime : undefined,
    elapsedSecs: typeof image.elapsedSecs === "number" ? image.elapsedSecs : undefined,
    elapsedUpdatedAt: typeof image.elapsedUpdatedAt === "number" ? image.elapsedUpdatedAt : undefined,
    durationMs: typeof image.durationMs === "number" ? image.durationMs : undefined,
  };
  if (normalizedUrl && normalized.b64_json) {
    delete normalized.b64_json;
  }
  if (image.status === "loading" || image.status === "error" || image.status === "success") {
    return normalized;
  }
  return {
    ...normalized,
    status: image.b64_json || image.url ? "success" : "loading",
  };
}

function normalizeReferenceImage(image: StoredReferenceImage): StoredReferenceImage {
  return {
    name: image.name || "reference.png",
    type: image.type || "image/png",
    dataUrl: typeof image.dataUrl === "string" && image.dataUrl ? image.dataUrl : undefined,
    url: typeof image.url === "string" && image.url ? image.url : undefined,
    rel: typeof image.rel === "string" && image.rel ? image.rel : undefined,
    expiresAt: typeof image.expiresAt === "string" ? image.expiresAt : undefined,
    expired: image.expired === true,
  };
}

function dataUrlMimeType(dataUrl: string) {
  const match = dataUrl.match(/^data:(.*?);base64,/);
  return match?.[1] || "image/png";
}

function getLegacyReferenceImages(source: Record<string, unknown>): StoredReferenceImage[] {
  if (Array.isArray(source.referenceImages)) {
    return source.referenceImages
      .filter((image): image is StoredReferenceImage => {
        if (!image || typeof image !== "object") {
          return false;
        }
        const candidate = image as StoredReferenceImage;
        return (
          (typeof candidate.dataUrl === "string" && candidate.dataUrl.length > 0) ||
          (typeof candidate.url === "string" && candidate.url.length > 0)
        );
      })
      .map(normalizeReferenceImage);
  }

  if (source.sourceImage && typeof source.sourceImage === "object") {
    const image = source.sourceImage as { dataUrl?: unknown; fileName?: unknown };
    if (typeof image.dataUrl === "string" && image.dataUrl) {
      return [
        {
          name: typeof image.fileName === "string" && image.fileName ? image.fileName : "reference.png",
          type: dataUrlMimeType(image.dataUrl),
          dataUrl: image.dataUrl,
        },
      ];
    }
  }

  return [];
}

function normalizeTurn(turn: ImageTurn & Record<string, unknown>): ImageTurn {
  const normalizedImages = Array.isArray(turn.images) ? turn.images.map(normalizeStoredImage) : [];
  const derivedStatus: ImageTurnStatus =
    normalizedImages.some((image) => image.status === "loading")
      ? "generating"
      : normalizedImages.some((image) => image.status === "error")
        ? "error"
        : "success";

  return {
    id: String(turn.id || `${Date.now()}`),
    prompt: String(turn.prompt || ""),
    model: (turn.model as ImageModel) || "gpt-image-2",
    mode: turn.mode === "edit" ? "edit" : "generate",
    referenceImages: getLegacyReferenceImages(turn),
    count: Math.max(1, Number(turn.count || normalizedImages.length || 1)),
    size: typeof turn.size === "string" ? turn.size : "",
    ratio: typeof turn.ratio === "string" && turn.ratio ? turn.ratio : "1:1",
    tier: typeof turn.tier === "string" && turn.tier ? turn.tier : "1k",
    quality: typeof turn.quality === "string" && turn.quality ? turn.quality : "auto",
    images: normalizedImages,
    createdAt: String(turn.createdAt || new Date().toISOString()),
    status:
      turn.status === "queued" ||
      turn.status === "generating" ||
      turn.status === "success" ||
      turn.status === "error"
        ? turn.status
        : derivedStatus,
    error: typeof turn.error === "string" ? turn.error : undefined,
    promptDeleted: turn.promptDeleted === true,
    resultsDeleted: turn.resultsDeleted === true,
  };
}

function normalizeConversation(conversation: ImageConversation & Record<string, unknown>): ImageConversation {
  const turns = Array.isArray(conversation.turns)
    ? conversation.turns.map((turn) => normalizeTurn(turn as ImageTurn & Record<string, unknown>))
    : [
        normalizeTurn({
          id: String(conversation.id || `${Date.now()}`),
          prompt: String(conversation.prompt || ""),
          model: (conversation.model as ImageModel) || "gpt-image-2",
          mode: conversation.mode === "edit" ? "edit" : "generate",
          referenceImages: getLegacyReferenceImages(conversation),
          count: Number(conversation.count || 1),
          size: typeof conversation.size === "string" ? conversation.size : "",
          ratio: typeof conversation.ratio === "string" && conversation.ratio ? conversation.ratio : "1:1",
          tier: typeof conversation.tier === "string" && conversation.tier ? conversation.tier : "1k",
          quality: typeof conversation.quality === "string" && conversation.quality ? conversation.quality : "auto",
          images: Array.isArray(conversation.images) ? (conversation.images as StoredImage[]) : [],
          createdAt: String(conversation.createdAt || new Date().toISOString()),
          status:
            conversation.status === "generating" || conversation.status === "success" || conversation.status === "error"
              ? conversation.status
              : "success",
          error: typeof conversation.error === "string" ? conversation.error : undefined,
        }),
      ];
  const lastTurn = turns.length > 0 ? turns[turns.length - 1] : null;

  return {
    id: String(conversation.id || `${Date.now()}`),
    title: String(conversation.title || ""),
    createdAt: String(conversation.createdAt || lastTurn?.createdAt || new Date().toISOString()),
    updatedAt: String(conversation.updatedAt || lastTurn?.createdAt || new Date().toISOString()),
    turns,
  };
}

function sortImageConversations(conversations: ImageConversation[]): ImageConversation[] {
  return [...conversations].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

function getTimestamp(value: string) {
  const time = new Date(value).getTime();
  return Number.isFinite(time) ? time : 0;
}

function pickLatestConversation(current: ImageConversation, next: ImageConversation) {
  return getTimestamp(next.updatedAt) >= getTimestamp(current.updatedAt) ? next : current;
}

function queueImageConversationWrite<T>(operation: () => Promise<T>): Promise<T> {
  const result = imageConversationWriteQueue.then(operation);
  imageConversationWriteQueue = result.then(
    () => undefined,
    () => undefined,
  );
  return result;
}

async function readStoredImageConversations(): Promise<ImageConversation[]> {
  const items =
    (await imageConversationStorage.getItem<Array<ImageConversation & Record<string, unknown>>>(
      SERVER_IMAGE_CONVERSATIONS_CACHE_KEY,
    )) || [];
  return items.map(normalizeConversation);
}

export async function listImageConversations(): Promise<ImageConversation[]> {
  try {
    const response = await httpRequest<{ items: Array<ImageConversation & Record<string, unknown>> }>(
      "/api/image-conversations",
    );
    const items = sortImageConversations(response.items.map(normalizeConversation));
    await imageConversationStorage.setItem(SERVER_IMAGE_CONVERSATIONS_CACHE_KEY, items);
    return items;
  } catch (error) {
    const cached = sortImageConversations(await readStoredImageConversations());
    if (cached.length > 0) {
      return cached;
    }
    throw error;
  }
}

export async function saveImageConversations(conversations: ImageConversation[]): Promise<void> {
  await queueImageConversationWrite(async () => {
    for (const conversation of conversations.map(normalizeConversation)) {
      await upsertServerConversation(conversation);
    }
  });
}

export async function saveImageConversation(conversation: ImageConversation): Promise<void> {
  await queueImageConversationWrite(async () => {
    await upsertServerConversation(normalizeConversation(conversation));
  });
}

async function upsertServerConversation(conversation: ImageConversation): Promise<ImageConversation> {
  const response = await httpRequest<{ item: ImageConversation & Record<string, unknown> }>(
    `/api/image-conversations/${encodeURIComponent(conversation.id)}`,
    {
      method: "PUT",
      body: conversation,
    },
  );
  const saved = normalizeConversation(response.item);
  await mergeCachedConversation(saved);
  return saved;
}

async function mergeCachedConversation(conversation: ImageConversation): Promise<void> {
    const items = await readStoredImageConversations();
    const nextConversation = normalizeConversation(conversation);
    const current = items.find((item) => item.id === nextConversation.id);
    const persistedConversation = current ? pickLatestConversation(current, nextConversation) : nextConversation;
    const nextItems = sortImageConversations([
      persistedConversation,
      ...items.filter((item) => item.id !== persistedConversation.id),
    ]);
    await imageConversationStorage.setItem(SERVER_IMAGE_CONVERSATIONS_CACHE_KEY, nextItems);
}

export async function renameImageConversation(id: string, title: string): Promise<void> {
  await queueImageConversationWrite(async () => {
    const response = await httpRequest<{ item: ImageConversation & Record<string, unknown> }>(
      `/api/image-conversations/${encodeURIComponent(id)}/rename`,
      {
        method: "PATCH",
        body: { title },
      },
    );
    await mergeCachedConversation(normalizeConversation(response.item));
  });
}

export async function deleteImageConversation(id: string): Promise<void> {
  await queueImageConversationWrite(async () => {
    await httpRequest<{ ok: boolean }>(`/api/image-conversations/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
    const items = await readStoredImageConversations();
    await imageConversationStorage.setItem(
      SERVER_IMAGE_CONVERSATIONS_CACHE_KEY,
      items.filter((item) => item.id !== id),
    );
  });
}

export async function clearImageConversations(): Promise<void> {
  await queueImageConversationWrite(async () => {
    await httpRequest<{ ok: boolean; removed: number }>("/api/image-conversations/clear", { method: "POST" });
    await imageConversationStorage.removeItem(SERVER_IMAGE_CONVERSATIONS_CACHE_KEY);
  });
}

export async function downloadImageConversationImages(conversationId: string, imageIds?: string[]): Promise<void> {
  const response = await request.post(
    `/api/image-conversations/${encodeURIComponent(conversationId)}/download`,
    { image_ids: imageIds && imageIds.length > 0 ? imageIds : undefined },
    { responseType: "blob" },
  );
  const blob = response.data as Blob;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = imageIds && imageIds.length > 0 ? "selected-images.zip" : "conversation-images.zip";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function getImageConversationStats(conversation: ImageConversation | null): ImageConversationStats {
  if (!conversation) {
    return { queued: 0, running: 0 };
  }

  return conversation.turns.reduce(
    (acc, turn) => {
      if (turn.resultsDeleted) {
        return acc;
      }
      if (turn.status === "queued") {
        acc.queued += 1;
      } else if (turn.status === "generating") {
        acc.running += 1;
      }
      return acc;
    },
    { queued: 0, running: 0 },
  );
}
