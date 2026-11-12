/**
 * SSOT ⇄ Pi 接入扩展（ssot-kit · 2026-10-25）
 *
 * 两件事：
 *  ① 开机上下文：会话开局跑 `<ROOT>/tools/hooks/session-start.sh`（kit 同源 hook 脚本），
 *     把「SSOT 指针 + 项目 .memory 现场态」注入 system prompt（sections，稳定段 → 缓存友好）。
 *  ② 回忆触发：用户消息命中回忆/取证句式时，跑本地语义检索（sp_semantic，top-3）注入本轮。
 *
 * ROOT = $SSOT_ROOT 或 ~/ssot。检索需 llama-server:8399（不在则跳过，不拉起）。
 * 开关：SSOT_PI_BOOT=0 关全部；SSOT_PI_RECALL=0 关检索；SSOT_PI_VERBOSE=1 逐调用日志。
 * 日志：~/.cache/ssot-pi-boot/debug.log
 *
 * 安装：bash scripts/install-pi-extension.sh（复制到 ~/.pi/agent/extensions/，改完 /reload）。
 */
import { execFile } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const HOME = process.env.HOME ?? homedir();
const ROOT = process.env.SSOT_ROOT ?? join(HOME, "ssot");
const BOOT_SCRIPT = join(ROOT, "tools/hooks/session-start.sh");
const SEMANTIC = join(ROOT, "tools/sp_semantic.py");
const RECALL_FILE = join(ROOT, "tools/recall-phrases.json");
const EMBED_HEALTH = "http://127.0.0.1:8399/health";
const DBG_DIR = join(HOME, ".cache/ssot-pi-boot");
const DBG_FILE = join(DBG_DIR, "debug.log");

const ENABLED = process.env.SSOT_PI_BOOT !== "0";
const RECALL = process.env.SSOT_PI_RECALL !== "0";
const VERBOSE = process.env.SSOT_PI_VERBOSE === "1";

// 回忆句式单一真源 = <ROOT>/tools/recall-phrases.json（缺文件/坏 JSON 回退内嵌副本）
const FALLBACK_RECALL_RE =
	/还记得|记得吗|以前(说|提|做|那个|我们|的)|上次(说|提|做|讨论|那个|的)|之前(说|提|做|讨论|那个|提到|的)|早先|前面说过|回顾一下|找一找.*(之前|以前|历史|那个)|(之前|以前)的(会话|记录|讨论)|那时候我们|当时我们|历史(会话|记录|里)/;

function dbg(msg: string) {
	try {
		mkdirSync(DBG_DIR, { recursive: true });
		appendFileSync(DBG_FILE, `${new Date().toISOString()} ${msg}\n`);
	} catch {}
}
function vdbg(msg: string) {
	if (VERBOSE) dbg(msg);
}

function loadRecallRe(): { re: RegExp; src: string } {
	try {
		const d = JSON.parse(readFileSync(RECALL_FILE, "utf8"));
		if (d && typeof d.regex === "string" && d.regex) return { re: new RegExp(d.regex, "u"), src: "json" };
		dbg("recall: json 无 regex 字段，回退内嵌副本");
	} catch (e) {
		dbg(`recall: 读 ${RECALL_FILE} 失败（${e}），回退内嵌副本`);
	}
	return { re: FALLBACK_RECALL_RE, src: "fallback" };
}

function run(cmd: string, args: string[], cwd: string, timeout: number): Promise<string> {
	return new Promise((resolve) => {
		try {
			execFile(cmd, args, { cwd, timeout, maxBuffer: 4 * 1024 * 1024 }, (_err, stdout) => {
				resolve(stdout ? String(stdout) : "");
			});
		} catch {
			resolve("");
		}
	});
}

async function embedUp(): Promise<boolean> {
	try {
		const r = await fetch(EMBED_HEALTH, { signal: AbortSignal.timeout(1500) });
		return r.ok;
	} catch {
		return false;
	}
}

export default function ssotBootExtension(pi: ExtensionAPI) {
	let bootText = "";
	let bootCwd = "";
	let recallRe: { re: RegExp; src: string } | null = null;
	let lastQuery = "";

	pi.on("session_start", async (_event, ctx) => {
		if (!ENABLED) return;
		bootCwd = ctx.cwd;
		bootText = "";
		if (!existsSync(BOOT_SCRIPT)) {
			dbg(`boot: 脚本缺失 ${BOOT_SCRIPT}`);
			return;
		}
		bootText = (await run("bash", [BOOT_SCRIPT], ctx.cwd, 8000)).trim();
		dbg(`boot: cwd=${ctx.cwd} bytes=${bootText.length}`);
	});

	pi.on("before_agent_start", async (event, ctx) => {
		if (!ENABLED) return;
		try {
			if (ctx.cwd !== bootCwd && existsSync(BOOT_SCRIPT)) {
				bootCwd = ctx.cwd;
				bootText = (await run("bash", [BOOT_SCRIPT], ctx.cwd, 8000)).trim();
				dbg(`boot: cwd 变更重跑 cwd=${ctx.cwd} bytes=${bootText.length}`);
			}
			if (bootText) event.systemPromptOptions.sections["ssot_boot"] = bootText;
		} catch (e) {
			dbg(`boot: 注入失败 ${e}`);
		}

		if (!RECALL || event.messageType !== "user") return;
		const prompt = event.prompt ?? "";
		if (!prompt || prompt.length > 4000) return;
		recallRe ??= loadRecallRe();
		if (!recallRe.re.test(prompt)) return;
		const q = prompt.replace(/\s+/g, " ").trim().slice(0, 200);
		if (!q || q === lastQuery) return;
		if (!existsSync(SEMANTIC)) return;
		try {
			if (!(await embedUp())) {
				dbg(`recall: :8399 未起，跳过 q=${q.slice(0, 40)}`);
				return;
			}
			const out = await run("python3", [SEMANTIC, q, "--expand", "--top", "3"], ROOT, 40000);
			// sp_semantic 头部 = query/commit 一行 + 空行；结果从第 3 行起，取 12 行
			const body = out.split("\n").slice(2, 14).join("\n").trim();
			if (!body) return;
			lastQuery = q;
			event.systemPromptOptions.sections["ssot_recall"] =
				`【记忆检索·自动触发（命中回忆句式 · 本地库 top-3 · query: ${q}）】\n${body}\n` +
				`--（出处见 path:line；要深查可跑：python3 ${join(ROOT, "tools/sp_semantic.py")} "<问题>" --expand）`;
			dbg(`recall: hit q=${q.slice(0, 60)} bytes=${body.length} src=${recallRe.src}`);
		} catch (e) {
			dbg(`recall: 失败 ${e}`);
		}
	});
}
