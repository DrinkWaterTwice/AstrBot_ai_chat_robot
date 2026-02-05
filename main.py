from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from .tts.tts_api import TTSClient
from astrbot.api.provider import LLMResponse, ProviderRequest
from .process_llm_request import ProcessLLMRequest
from .long_term_memory import LongTermMemory


@register("helloworld", "YourName", "一个简单的 Hello World 插件", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.context = context
        self.proc_llm_req = ProcessLLMRequest(self.context)
        self.ltm = None
        try:
            self.ltm = LongTermMemory(self.context.astrbot_config_mgr, self.context)
        except BaseException as e:
            logger.error(f"聊天增强 err: {e}")

    def ltm_enabled(self, event: AstrMessageEvent):
        ltmse = self.context.get_config(umo=event.unified_msg_origin)[
            "provider_ltm_settings"
        ]
        return ltmse["group_icl_enable"] or ltmse["active_reply"]["enable"]

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
    # 注册指令的装饰器。指令名为 helloworld。注册成功后，发送 `/helloworld` 就会触发这个指令，并回复 `你好, {user_name}!`
    @filter.command("luo")
    async def yuyin(self, event: AstrMessageEvent):
        """这是一个语音指令, 会将用户发送的消息转换为语音并回复""" # 这是 handler 的描述，将会被解析方便用户了解插件内容。建议填写。
        message_str = event.message_str # 用户发的纯文本消息字符串

        message_str = message_str.removeprefix("luo ") # 去掉命令前缀，获取实际消息内容


        session_curr_cid = await self.context.conversation_manager.get_curr_conversation_id(
            event.unified_msg_origin,
        )
        conv = await self.context.conversation_manager.get_conversation(
            event.unified_msg_origin,
            session_curr_cid,
        )

        yield event.request_llm(
            prompt=message_str,
            func_tool_manager=self.context.get_llm_tool_manager(),
            session_id=event.session_id,
            conversation=conv,
        )


        # logger.info(llm_resp)





    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""

    @filter.on_llm_request()
    async def decorate_llm_req(self, event: AstrMessageEvent, req: ProviderRequest):
        """在请求 LLM 前注入人格信息、Identifier、时间、回复内容等 System Prompt"""
        await self.proc_llm_req.process_llm_request(event, req)

        if self.ltm and self.ltm_enabled(event):
            try:
                await self.ltm.on_req_llm(event, req)
            except BaseException as e:
                logger.error(f"ltm: {e}")

    @filter.on_llm_response()
    async def record_llm_resp_to_ltm(self, event: AstrMessageEvent, resp: LLMResponse):
        """在 LLM 响应后记录对话"""
        if self.ltm and self.ltm_enabled(event):
            try:
                await self.ltm.after_req_llm(event, resp)
            except Exception as e:
                logger.error(f"ltm: {e}")

    @filter.after_message_sent()
    async def after_message_sent(self, event: AstrMessageEvent):
        """消息发送后处理"""
        if self.ltm and self.ltm_enabled(event):
            try:
                clean_session = event.get_extra("_clean_ltm_session", False)
                if clean_session:
                    await self.ltm.remove_session(event)
            except Exception as e:
                logger.error(f"ltm: {e}")

    @filter.on_llm_response()
    async def handle_message(self, event: AstrMessageEvent, resp: LLMResponse):
        logger.info(resp.completion_text)
        client = TTSClient()
        client.synthesize_and_play_realtime(resp.completion_text)  # 调用 TTSClient 将文本转换为语音并发送