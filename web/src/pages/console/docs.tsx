import { Link } from "react-router-dom";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CodeBlock, PageHeader } from "@/components/ui/misc";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export function ConsoleDocs() {
  const base = window.location.origin;
  const steps = [
    { n: 1, t: "创建密钥", d: <>在 <Link className="underline underline-offset-4" to="/console/keys">API 密钥</Link> 页创建，形如 sk-lr-…</> },
    { n: 2, t: "替换地址", d: <>把客户端的 Base URL 改为 <code className="font-mono">{base}/v1</code></> },
    { n: 3, t: "选择模型", d: <>model 填 <code className="font-mono">auto</code> 自动路由，或指定具体模型</> },
  ];
  return (
    <>
      <PageHeader title="快速开始" desc="网关同时兼容 OpenAI Chat Completions、OpenAI Responses 和 Anthropic Messages 三种协议。" />
      <div className="grid gap-4 sm:grid-cols-3">
        {steps.map((s) => (
          <Card key={s.n} className="p-5">
            <div className="flex size-6 items-center justify-center rounded-full bg-foreground text-xs font-semibold text-background">{s.n}</div>
            <div className="mt-3 font-medium">{s.t}</div>
            <div className="mt-1 text-[13px] text-muted-foreground">{s.d}</div>
          </Card>
        ))}
      </div>
      <Card className="mt-4">
        <CardHeader>
          <CardTitle>示例</CardTitle>
          <CardDescription>把 sk-lr-xxx 换成你自己的密钥</CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="curl">
            <TabsList>
              <TabsTrigger value="curl">curl</TabsTrigger>
              <TabsTrigger value="python">OpenAI SDK</TabsTrigger>
              <TabsTrigger value="claude">Claude Code</TabsTrigger>
              <TabsTrigger value="codex">Codex CLI</TabsTrigger>
            </TabsList>
            <TabsContent value="curl">
              <CodeBlock
                lang="bash"
                code={`curl ${base}/v1/chat/completions \\
  -H "Authorization: Bearer sk-lr-xxx" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "auto",
    "messages": [{"role": "user", "content": "用一句话介绍你自己"}]
  }'`}
              />
            </TabsContent>
            <TabsContent value="python">
              <CodeBlock
                lang="python"
                code={`from openai import OpenAI

client = OpenAI(base_url="${base}/v1", api_key="sk-lr-xxx")

resp = client.chat.completions.create(
    model="auto",            # 或 auto:quality_first / gpt-4o / claude-sonnet-4-5 …
    messages=[{"role": "user", "content": "你好"}],
)
print(resp.choices[0].message.content)`}
              />
            </TabsContent>
            <TabsContent value="claude">
              <CodeBlock
                lang="bash"
                code={`export ANTHROPIC_BASE_URL="${base}"
export ANTHROPIC_AUTH_TOKEN="sk-lr-xxx"
export ANTHROPIC_MODEL="auto"
claude`}
              />
            </TabsContent>
            <TabsContent value="codex">
              <CodeBlock
                lang="toml  ·  ~/.codex/config.toml"
                code={`model = "auto"
model_provider = "autollm"

[model_providers.autollm]
name = "AutoLLM Gate"
base_url = "${base}/v1"
env_key = "AUTOLLM_API_KEY"
wire_api = "responses"`}
              />
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
      <Card className="mt-4">
        <CardHeader>
          <CardTitle>响应头</CardTitle>
          <CardDescription>每个响应都会告诉你网关实际选用了哪个模型、为什么</CardDescription>
        </CardHeader>
        <CardContent>
          <CodeBlock
            code={`X-Router-Model: deepseek-chat        实际使用的模型
X-Router-Provider: deepseek          上游提供方
X-Router-Strategy: cost_optimized    路由策略
X-Router-Reason: task=chat; …        选择理由（含降级信息）
X-Router-Attempts: 1                 尝试次数（>1 表示发生了自动切换）`}
          />
        </CardContent>
      </Card>
    </>
  );
}
