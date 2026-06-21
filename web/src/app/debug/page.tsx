"use client";

import { useState } from "react";
import { LoaderCircle } from "lucide-react";

import { useAuthGuard } from "@/lib/use-auth-guard";
import { cn } from "@/lib/utils";

import { ChatPanel } from "./components/chat-panel";
import { PptPanel } from "./components/ppt-panel";
import { PsdPanel } from "./components/psd-panel";
import { SearchPanel } from "./components/search-panel";
import { SkillPanel } from "./components/skill-panel";

const tabs = [
  { value: "skills", title: "Skill安装" },
  { value: "search", title: "联网搜索" },
  { value: "ppt", title: "PPT生成" },
  { value: "psd", title: "PSD生成" },
  { value: "chat", title: "对话" },
];

type DebugTab = (typeof tabs)[number]["value"];

export default function DebugPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);
  const [activeTab, setActiveTab] = useState<DebugTab>("skills");

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[calc(100dvh-4rem)] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="mx-auto flex min-h-[calc(100dvh-4rem)] w-full max-w-[1600px] min-w-0 flex-col gap-4 px-0 pt-3 pb-6 md:px-8">
      <div className="min-w-0 px-1">
        <div className="grid min-h-10 w-full grid-cols-5 items-center rounded-xl sm:inline-flex sm:w-fit">
          {tabs.map(({ value, title }) => (
            <button
              key={value}
              type="button"
              className={cn(
                "relative inline-flex h-10 min-w-0 items-center justify-center rounded-lg border border-transparent px-1.5 text-[13px] leading-none font-medium whitespace-nowrap text-stone-500 transition hover:text-stone-950 sm:px-3 sm:text-sm dark:text-stone-400 dark:hover:text-stone-100",
                activeTab === value && "text-stone-950 after:absolute after:inset-x-1 after:bottom-0 after:h-0.5 after:rounded-full after:bg-stone-950 dark:text-stone-50 dark:after:bg-stone-50",
              )}
              onClick={() => setActiveTab(value)}
            >
              {title}
            </button>
          ))}
        </div>
      </div>
      <div hidden={activeTab !== "skills"}>
        <SkillPanel />
      </div>
      <div hidden={activeTab !== "search"} className="min-h-0">
        <SearchPanel />
      </div>
      <div hidden={activeTab !== "ppt"} className="min-h-0">
        <PptPanel />
      </div>
      <div hidden={activeTab !== "psd"} className="min-h-0">
        <PsdPanel />
      </div>
      <div hidden={activeTab !== "chat"} className="min-h-0">
        <ChatPanel />
      </div>
    </div>
  );
}
