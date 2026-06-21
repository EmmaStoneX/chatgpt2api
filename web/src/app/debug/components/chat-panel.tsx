"use client";

import { useEffect, useState } from "react";
import { LoaderCircle, Send } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { fetchModels } from "@/lib/api";
import { httpRequest } from "@/lib/request";

import { pretty, type ChatCompletionResponse, type ChatMessage } from "./types";

const chatModelOptions = [
  { value: "auto", label: "auto" },
  { value: "gpt-5", label: "gpt-5" },
  { value: "gpt-5-1", label: "gpt-5-1" },
  { value: "gpt-5-2", label: "gpt-5-2" },
  { value: "gpt-5-3", label: "gpt-5-3" },
  { value: "gpt-5-3-mini", label: "gpt-5-3-mini" },
  { value: "gpt-5-5", label: "gpt-5-5" },
  { value: "gpt-5-mini", label: "gpt-5-mini" },
];

export function ChatPanel() {
  const [model, setModel] = useState("auto");
  const [modelOptions, setModelOptions] = useState(chatModelOptions);
  const [isLoadingModels, setIsLoadingModels] = useState(false);
  const [modelLoadError, setModelLoadError] = useState("");
  const [input, setInput] = useState("你好，先记住我的项目叫 chatgpt2api。");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [raw, setRaw] = useState<ChatCompletionResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setIsLoadingModels(true);
    setModelLoadError("");
    fetchModels()
      .then((data) => {
        if (cancelled) return;
        const ids = Array.from(new Set((data.data || []).map((item) => item.id).filter(Boolean)));
        if (!ids.includes("auto")) {
          ids.unshift("auto");
        }
        if (ids.length > 0) {
          setModelOptions(ids.map((id) => ({ value: id, label: id })));
          if (!ids.includes(model)) {
            setModel(ids[0]);
          }
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setModelLoadError(err instanceof Error ? err.message : "模型列表加载失败，已使用默认列表");
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoadingModels(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const sendChat = async () => {
    const content = input.trim();
    if (!content) return;
    const nextMessages: ChatMessage[] = [...messages, { role: "user", content }];
    setMessages(nextMessages);
    setInput("");
    setLoading(true);
    setError("");
    try {
      const result = await httpRequest<ChatCompletionResponse>("/v1/chat/completions", {
        method: "POST",
        body: { model: model.trim() || "auto", messages: nextMessages },
        timeout: 60000,
      });
      setRaw(result);
      setMessages([...nextMessages, { role: "assistant", content: String(result.choices?.[0]?.message?.content || "") }]);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message.includes("timeout") || message.includes("exceeded") ? "请求超过 60 秒未返回，请检查账号、代理或上游服务状态。" : message);
    } finally {
      setLoading(false);
    }
  };

  const clearChat = () => {
    setMessages([]);
    setRaw(null);
    setError("");
  };

  return (
    <div className="grid min-h-0 w-full grid-cols-1 gap-5 lg:h-full lg:grid-cols-[minmax(280px,360px)_minmax(0,1fr)] lg:gap-8">
      <section className="flex min-h-0 flex-col lg:border-r lg:border-stone-200/70 lg:pr-8 dark:lg:border-white/10">
        <div className="border-b border-stone-200/70 pb-3 dark:border-white/10">
          <h2 className="text-sm font-medium text-stone-500 dark:text-stone-400">请求</h2>
        </div>
        <div className="min-h-0 flex-1 space-y-4 overflow-auto pt-4">
          <div className="space-y-2">
            <Label htmlFor="chat-model">Model</Label>
            <Select value={model} onValueChange={setModel}>
              <SelectTrigger id="chat-model" className="border-stone-200/70 bg-transparent shadow-none dark:border-white/10">
                <SelectValue placeholder="选择模型" />
              </SelectTrigger>
              <SelectContent>
                {modelOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="text-xs text-stone-400">
              {isLoadingModels ? "正在从 /v1/models 加载模型..." : modelLoadError ? modelLoadError : "模型列表来自 /v1/models。"}
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="chat-input">Message</Label>
            <Textarea id="chat-input" value={input} onChange={(event) => setInput(event.target.value)} className="min-h-32 border-stone-200/70 bg-transparent shadow-none dark:border-white/10" />
          </div>
          <div className="flex gap-2">
            <Button size="sm" onClick={() => void sendChat()} disabled={loading || !input.trim()}>
              {loading ? <LoaderCircle className="animate-spin" /> : <Send />}
              发送
            </Button>
            <Button size="sm" variant="outline" onClick={clearChat}>
              清空
            </Button>
          </div>
          {error ? <div className="rounded-xl border border-rose-200 bg-rose-50/60 px-3 py-2 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/20 dark:text-rose-300">{error}</div> : null}
          <Textarea value={raw ? pretty(raw) : "{\n  \"messages\": []\n}"} readOnly className="min-h-72 resize-none border-stone-200/70 bg-stone-50/50 p-4 font-mono text-xs leading-5 text-stone-600 shadow-none dark:border-white/10 dark:bg-white/[0.03] dark:text-stone-300" />
        </div>
      </section>
      <section className="flex min-h-0 flex-col">
        <div className="border-b border-stone-200/70 pb-3 dark:border-white/10">
          <h2 className="text-sm font-medium text-stone-500 dark:text-stone-400">对话</h2>
        </div>
        <div className="min-h-0 flex-1 space-y-4 overflow-auto pt-4">
          {messages.length ? messages.map((message, index) => (
            <div key={`${message.role}-${index}`} className="space-y-1.5 text-sm">
              <div className="text-xs font-medium uppercase tracking-wide text-stone-400 dark:text-stone-500">{message.role}</div>
              <div className="whitespace-pre-wrap leading-7 text-stone-700 dark:text-stone-300">{message.content}</div>
            </div>
          )) : (
            <div className="flex h-full items-center justify-center text-sm text-stone-400 dark:text-stone-500">暂无对话消息</div>
          )}
        </div>
      </section>
    </div>
  );
}
