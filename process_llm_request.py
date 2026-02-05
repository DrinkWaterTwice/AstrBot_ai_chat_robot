import builtins
import copy
import datetime
import zoneinfo

from astrbot.api import logger, sp, star
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Image, Reply
from astrbot.api.provider import Provider, ProviderRequest
from astrbot.core.agent.message import TextPart
from astrbot.core.pipeline.process_stage.utils import (
    CHATUI_SPECIAL_DEFAULT_PERSONA_PROMPT,
    LOCAL_EXECUTE_SHELL_TOOL,
    LOCAL_PYTHON_TOOL,
)
from astrbot.core.provider.func_tool_manager import ToolSet
from astrbot.core.skills.skill_manager import SkillManager, build_skills_prompt


class ProcessLLMRequest:

    def __init__(self, context: star.Context):
        self.ctx = context
        cfg = context.get_config()
        self.timezone = cfg.get("timezone", None)
        if not self.timezone:
            self.timezone = None

        self.skill_manager = SkillManager()

    def _apply_local_env_tools(self, req: ProviderRequest):
        """Add local environment tools to the provider request."""
        if req.func_tool is None:
            req.func_tool = ToolSet()
        # req.func_tool.add_tool(LOCAL_EXECUTE_SHELL_TOOL)
        req.func_tool.add_tool(LOCAL_PYTHON_TOOL)



    """
    1. 获取人格, 先后顺序为 1. 用户指定人格 2. 会话指定人格 3. 默认人格 4. 默认人格配置， 使用过滤器根据id过滤出第一个id对应的人格
    2. 从人格获取预设对话，注入到请求上下文开头
    3. 获取技能配置，确认是本地还是沙盒（沙盒应该还没有），如果是沙盒，检查沙盒是否启用
    4. 获取skills列表，注入到系统提示词中
     5. 根据人格配置的工具列表，或者全局工具列表，注入工具列表（该列表和请求关联）

    """

    async def _ensure_persona(
        self,
        req: ProviderRequest,
        cfg: dict,
        umo: str,
        platform_type: str,
        event: AstrMessageEvent,
    ):
        # this conversation means context of request
        if not req.conversation:
            return
        # persona inject
        persona_id = (
            await sp.get_async(
                scope="umo", scope_id=umo, key="session_service_config", default={}
            )
        ).get("persona_id", None)

        if not persona_id:
            persona_id = req.conversation.persona_id or cfg.get("default_persona_id")
            if not persona_id and persona_id != "[%None]":  # [%None] 为用户取消人格
                default_persona_id = self.ctx.persona_manager.selected_default_persona_v3
                if default_persona_id:
                    persona_id = default_persona_id
                    logger.info(
                        f"Using globally selected default persona {persona_id} for conversation {umo}"
                    )
        persona = next(
            builtins.filter(
                lambda persona: persona['name'] == persona_id, self.ctx.persona_manager.personas_v3
            ),
            None
        )

        if persona:
            if prompt := persona["prompt"]:
                req.system_prompt = prompt
            if begin_dialogs := copy.deepcopy(persona["_begin_dialogs_processed"]):
                req.contexts[:0] = begin_dialogs

        runtime = self.skills_cfg.get("runtime", "local")
        skills = self.skill_manager.list_skills(active_only=True, runtime=runtime)
        
        if runtime == "sandbox" and not self.sandbox_cfg.get("enabled", False):
            logger.warning(
                "Skills runtime is set to sandbox, but sandbox mode is disabled, will skip skills prompt injection.",
            )
            req.system_prompt += "\n[Background: User added some skills, and skills runtime is set to sandbox, but sandbox mode is disabled. So skills will be unavailable.]\n"
        elif skills:
            if persona and persona.get("skills") is not None:
                if not persona["skills"]:
                    return  # 用户明确设置了 persona.skills 为空列表，表示不使用技能
                allowed = set(persona["skills"])
                skills = [skill for skill in skills if skill.name in allowed]
            if skills:
                req.system_prompt += build_skills_prompt(skills)
                # 是否开启了沙盒模式, 沙盒环境貌似还没有
                sandbox_enabled = self.sandbox_cfg.get("enable", False)
                if runtime == "local" and not sandbox_enabled:
                    self._apply_local_env_tools(req)
        tmgr = self.ctx.get_llm_tool_manager()
        if (persona and persona.get("tools") is None) or not persona:
            # 有人格但是没工具或者没有人格，才注入全局工具，否则使用人格指定的工具
            toolset = tmgr.get_full_tool_set()
            for tool in toolset:
                if not tool.active:
                    toolset.remove_tool(tool.name)

        else:
            toolset = ToolSet()
            if persona["tools"]:
                for tool_name in persona["tools"]:
                    tool = tmgr.get_func(tool_name)
                    if tool and tool.active:
                        toolset.add_tool(tool)
        if not req.func_tool:
            req.func_tool = toolset
        else:
            req.func_tool.merge(toolset)
        # 记录工具。暂时不知道有没有其他作用
        event.trace.record(
            "sel_persona", persona_id=persona_id, persona_toolset=toolset.names()
        )
        logger.debug(f"Tool set for persona {persona_id}: {toolset.names()}")

        """获取使用img_cap_prov_id指定的图片描述服务，并将其注入到请求中"""
    async def _ensure_img_caption(
        self,
        req: ProviderRequest,
        cfg: dict,
        img_cap_prov_id: str,
    ):
        try:
            # 这里返回的是服务处理后对于图片的描述文本
            caption = await self._request_img_caption(
                img_cap_prov_id,
                cfg,
                req.image_urls,
            )
            if caption:
                # 处理后的文本加入额外的用户消息内容部分列表，用于在用户消息后添加额外的内容块
                req.extra_user_content_parts.append(
                    TextPart(text=f"<image_caption>{caption}</image_caption>")
                )
                req.image_urls = []
        except Exception as e:
            logger.error(f"处理图片描述失败: {e}")

    """
    传入的是图片链接（以qq为例，应该是qq存起来后返回一个链接），
    返回的是模型对于图片的描述文本. 问题是为什么获取模型也是使用ctx
    """ 
    async def _request_img_caption(
        self,
        provider_id: str,
        cfg: dict,
        image_urls: list[str],
    ) -> str:
        if prov := self.ctx.get_provider_by_id(provider_id):
            if isinstance(prov, Provider):
                img_cap_prompt = cfg.get(
                    "image_caption_prompt",
                    "Please describe the image.",
                )
                logger.debug(f"Processing image caption with provider: {provider_id}")
                llm_resp = await prov.text_chat(
                    prompt=img_cap_prompt,
                    image_urls=image_urls,
                )
                return llm_resp.completion_text
            raise ValueError(
                f"Cannot get image caption because provider `{provider_id}` is not a valid Provider, it is {type(prov)}.",
            )
        raise ValueError(
            f"Cannot get image caption because provider `{provider_id}` is not exist.",
        )
    
    async def process_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        """在请求 LLM 前注入人格信息、Identifier、时间、回复内容等 System Prompt
        umo: unified_message_origin 值，用于获取特定会话的配置。
        """
        cfg: dict = self.ctx.get_config(umo=event.unified_msg_origin)[
            "provider_settings"
        ]
        self.skills_cfg = cfg.get("skills", {})
        self.sandbox_cfg = self.skills_cfg.get("sandbox", {})

        # prompt 前缀，用户可以通过在配置中加入{{prompt_prefix}}来注入一些固定的提示词到系统提示词开头
        if prefix := cfg.get("prompt_prefix"):
            # 支持 {{prompt}} 作为用户输入的占位符
            if "{{prompt}}" in prefix:
                req.prompt = prefix.replace("{{prompt}}", req.prompt)
            else:
                req.prompt = prefix + req.prompt
        # 收集系统提醒信息
        system_parts = []

        # user identifier （个人身份）
        if cfg.get("identifier"):
            user_id = event.message_obj.sender.user_id
            user_nickname = event.message_obj.sender.nickname
            system_parts.append(f"User ID: {user_id}, Nickname: {user_nickname}")

        # group name identifier （群组身份）
        if cfg.get("group_name_display") and event.message_obj.group_id:
            if not event.message_obj.group:
                logger.error(
                    f"Group name display enabled but group object is None. Group ID: {event.message_obj.group_id}"
                )
                return
            group_name = event.message_obj.group.group_name
            if group_name:
                system_parts.append(f"Group name: {group_name}")
        # 设置时区
        if cfg.get("datetime_system_prompt"):
            current_time = None
            if self.timezone:
                # 启用时区
                try:
                    now = datetime.datetime.now(zoneinfo.ZoneInfo(self.timezone))
                    current_time = now.strftime("%Y-%m-%d %H:%M (%Z)")
                except Exception as e:
                    logger.error(f"时区设置错误: {e}, 使用本地时区")
            if not current_time:
                current_time = (
                    datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M (%Z)")
                )
            system_parts.append(f"Current datetime: {current_time}")

        # 从配置中获取图片处理服务id
        img_cap_prov_id: str = cfg.get("default_image_caption_provider_id")
        if req.conversation:
            # 给这个对话加入人格
            platform_type = event.get_platform_name()
            await self._ensure_persona(
                req, cfg, event.unified_msg_origin, platform_type, event
            )

                        # image caption
            if img_cap_prov_id and req.image_urls:
                await self._ensure_img_caption(req, cfg, img_cap_prov_id)
            

            # 用户可能会@, 引用信息，因此需要处理
        quote= None
            
        for comp in event.message_obj.message:
            # 判断是引用消息(todo: 了解一下用什么方式判断是文本消息还是图片消息，或者二者皆有)
            # 这块应该和消息链解析有关
            if isinstance(comp, Reply):
                quote = comp
                break
        if quote:
            content_parts = []
            # 处理引用文本 图片 
            sender_info = (
                f"({quote.sender_nickname}): " if quote.sender_nickname else ""
            )
            message_str = quote.message_str or "[Empty Text]"
            content_parts.append(f"{sender_info}{message_str}")

            image_seg = None
            if quote.chain:
                for comp in quote.chain:
                    if isinstance(comp, Image):
                        image_seg = comp
                        break

            if image_seg:
                try:
                    # 找到可以生成图片描述的 provider
                    prov = None
                    if img_cap_prov_id:
                        prov = self.ctx.get_provider_by_id(img_cap_prov_id)
                    if prov is None:
                        # 如果没有配置专门的图片描述服务，就使用当前对话使用的聊天模型来生成图片描述
                        prov = self.ctx.get_using_provider(event.unified_msg_origin)

                    # 调用 provider 生成图片描述
                    if prov and isinstance(prov, Provider):
                        llm_resp = await prov.text_chat(
                            prompt="Please describe the image content.",
                            image_urls=[await image_seg.convert_to_file_path()],
                        )
                        if llm_resp.completion_text:
                            # 将图片描述作为文本添加到 content_parts
                            content_parts.append(
                                f"[Image Caption in quoted message]: {llm_resp.completion_text}"
                            )
                    else:
                        logger.warning(
                            "No provider found for image captioning in quote."
                        )
                except BaseException as e:
                    logger.error(f"处理引用图片失败: {e}")

            # 3. 将所有部分组合成文本并添加到 extra_user_content_parts 中
            # 确保引用内容被正确的标签包裹
            quoted_content = "\n".join(content_parts)
            # 确保所有内容都在<Quoted Message>标签内
            quoted_text = f"<Quoted Message>\n{quoted_content}\n</Quoted Message>"

            req.extra_user_content_parts.append(TextPart(text=quoted_text))

        # 统一包裹所有系统提醒
        if system_parts:
            system_content = (
                "<system_reminder>" + "\n".join(system_parts) + "</system_reminder>"
            )
            req.extra_user_content_parts.append(TextPart(text=system_content))
