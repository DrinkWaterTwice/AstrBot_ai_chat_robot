import requests

from typing import Generator
from io import BytesIO
import numpy as np
import soundfile as sf
import wave
from astrbot.api import logger

try:
    import sounddevice as sd
    AUDIO_AVAILABLE = True
    logger.debug("使用sounddevice进行音频播放")
except ImportError:
    AUDIO_AVAILABLE = False
    logger.debug("警告: 未找到sounddevice库，请安装: pip install sounddevice")


class TTSClient:
    def __init__(self, base_url: str = "http://127.0.0.1:9880"):
        """
        初始化TTS客户端
        
        Args:
            base_url: TTS API的基础URL
        """
        self.base_url = base_url
        self.tts_endpoint = f"{base_url}/tts"
    
    def synthesize_to_file(self, 
                          text: str,
                          ref_audio_path: str,
                          prompt_text: str,
                          output_path: str,
                          text_lang: str = "zh",
                          prompt_lang: str = "zh",
                          **kwargs) -> str:
        """
        将文本合成语音并保存到指定文件路径
        
        Args:
            text: 要合成的文本
            ref_audio_path: 参考音频路径
            prompt_text: 提示文本
            output_path: 输出文件路径
            text_lang: 文本语言
            prompt_lang: 提示文本语言
            **kwargs: 其他可选参数
            
        Returns:
            str: 成功时返回保存的文件路径
            
        Raises:
            Exception: 请求失败时抛出异常
        """
        # 构建请求数据
        logger.debug(f"开始合成音频: {text}")
        data = {
            "text": text,
            "text_lang": text_lang,
            "ref_audio_path": ref_audio_path,
            "prompt_lang": prompt_lang,
            "prompt_text": prompt_text,
            "text_split_method": kwargs.get("text_split_method", "cut5"),
            "batch_size": kwargs.get("batch_size", 1),
            "media_type": kwargs.get("media_type", "wav"),
            "streaming_mode": kwargs.get("streaming_mode", False)
        }
        
        # 添加其他可选参数
        optional_params = [
            "top_k", "top_p", "temperature", "batch_threshold", "split_bucket",
            "speed_factor", "fragment_interval", "seed", "parallel_infer",
            "repetition_penalty", "sample_steps", "super_sampling",
            "overlap_length", "min_chunk_length"
        ]
        
        for param in optional_params:
            if param in kwargs:
                data[param] = kwargs[param]
        
        # 发送POST请求
        response = requests.post(self.tts_endpoint, json=data)
        
        if response.status_code == 200:
            # 保存音频文件
            with open(output_path, "wb") as f:
                f.write(response.content)
            return output_path
        else:
            error_msg = response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text
            raise Exception(f"TTS请求失败: {error_msg}")
    
    def synthesize_to_stream(self,
                           text: str,
                           ref_audio_path: str,
                           prompt_text: str,
                           text_lang: str = "zh",
                           prompt_lang: str = "zh",
                           chunk_size: int = 1024,
                           **kwargs) -> Generator[bytes, None, None]:
        """
        将文本合成语音并通过流返回
        
        Args:
            text: 要合成的文本
            ref_audio_path: 参考音频路径
            prompt_text: 提示文本
            text_lang: 文本语言
            prompt_lang: 提示文本语言
            chunk_size: 流块大小
            **kwargs: 其他可选参数
            
        Yields:
            bytes: 音频数据块
            
        Raises:
            Exception: 请求失败时抛出异常
        """
        # 构建请求数据
        data = {
            "text": text,
            "text_lang": text_lang,
            "ref_audio_path": ref_audio_path,
            "prompt_lang": prompt_lang,
            "prompt_text": prompt_text,
            "text_split_method": kwargs.get("text_split_method", "cut5"),
            "batch_size": kwargs.get("batch_size", 1),
            "media_type": kwargs.get("media_type", "wav"),
            "streaming_mode": kwargs.get("streaming_mode", True)  # 流模式默认开启
        }
        
        # 添加其他可选参数
        optional_params = [
            "top_k", "top_p", "temperature", "batch_threshold", "split_bucket",
            "speed_factor", "fragment_interval", "seed", "parallel_infer",
            "repetition_penalty", "sample_steps", "super_sampling",
            "overlap_length", "min_chunk_length"
        ]
        
        for param in optional_params:
            if param in kwargs:
                data[param] = kwargs[param]
        
        # 发送POST请求（流模式）
        response = requests.post(self.tts_endpoint, json=data, stream=True)
        logger.debug(f"开始合成音频: {response.json()}")
        if response.status_code == 200:
            # 逐块返回音频数据
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    yield chunk
        else:
            error_msg = response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text
            raise Exception(f"TTS请求失败: {error_msg}")

    def synthesize_and_play_realtime(self, text, ref_audio_path="data/fairy_01_疑问.wav", prompt_text="替小师傅们买水，连续三次中了再来一瓶，这难道就是《天虚问道录》里所谓的气运之子的机缘？", **kwargs):
        """
        实时合成并播放TTS音频
        
        Args:
            tts_client: TTS客户端实例
            text: 要合成的文本
            ref_audio_path: 参考音频路径
            prompt_text: 提示文本
            **kwargs: 其他TTS参数
        """
        try:
            # 获取音频流
            audio_stream = self.synthesize_to_stream(
                text=text,
                ref_audio_path=ref_audio_path,
                prompt_text=prompt_text,
                streaming_mode=True,
                temperature=0.4,
                fragment_interval=0.45,
                **kwargs
            )
            
            # 创建播放器并播放
            player = TTSPlayer()
            player.play_stream(audio_stream)
            
        except Exception as e:
            logger.error(f"TTS处理或播放出错: {e}")

class TTSPlayer:
    def __init__(self):
        if not AUDIO_AVAILABLE:
            logger.error("错误: 音频播放不可用，请安装sounddevice库")
    
    def _is_wav_header(self, data: bytes) -> bool:
        """检查数据是否包含WAV头部"""
        return len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WAVE'
    
    def _extract_wav_parameters(self, wav_header: bytes):
        """
        从WAV头部提取音频参数
        """
        try:
            bio = BytesIO(wav_header)
            with wave.open(bio, 'rb') as wf:
                channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                sample_rate = wf.getframerate()
                return channels, sample_width, sample_rate
        except Exception as e:
            logger.error(f"解析WAV头部时出错: {e}")
            return 1, 2, 32000  # 默认参数
    
    def _convert_audio_bytes(self, audio_bytes: bytes, sample_width: int):
        """
        将音频字节转换为numpy数组
        """
        if not audio_bytes:
            return np.array([], dtype=np.float32)
            
        try:
            if sample_width == 1:
                # 8-bit unsigned
                data = np.frombuffer(audio_bytes, dtype=np.uint8)
                data = (data.astype(np.int16) - 128) * 256
            elif sample_width == 2:
                # 16-bit signed
                data = np.frombuffer(audio_bytes, dtype=np.int16)
            elif sample_width == 4:
                # 32-bit signed
                data = np.frombuffer(audio_bytes, dtype=np.int32)
                data = (data >> 16).astype(np.int16)
            else:
                raise ValueError(f"不支持的采样宽度: {sample_width}")
                
            return data.astype(np.float32) / 32768.0
        except Exception as e:
            logger.error(f"转换音频数据时出错: {e}")
            return np.array([], dtype=np.float32)
    
    def _find_data_chunk(self, wav_data: bytes):
        """
        在WAV数据中找到"data"块的起始位置
        """
        data_pos = wav_data.find(b'data')
        if data_pos != -1:
            # data块结构: "data" + 4字节长度 + 音频数据
            data_start = data_pos + 8
            return data_start
        return -1
    
    def play_stream(self, audio_stream_generator):
        """
        实时播放TTS流式音频
        
        Args:
            audio_stream_generator: TTS流生成器
        """
        if not AUDIO_AVAILABLE:
            logger.debug("错误: 音频播放不可用")
            return
            
        try:
            # 音频参数
            sample_rate = 32000
            sample_width = 2
            channels = 1
            
            # 存储所有音频数据
            audio_buffers = []
            first_chunk = True
            
            for chunk in audio_stream_generator:
                if first_chunk:
                    # 第一个块可能包含WAV头部
                    if self._is_wav_header(chunk):
                        logger.debug("检测到WAV头部")
                        # 提取音频参数
                        channels, sample_width, sample_rate = self._extract_wav_parameters(chunk)
                        logger.debug(f"音频参数: channels={channels}, sample_width={sample_width}, sample_rate={sample_rate}")
                        
                        # 找到音频数据的起始位置
                        data_start = self._find_data_chunk(chunk)
                        if data_start != -1 and data_start < len(chunk):
                            audio_data = chunk[data_start:]
                            if audio_data:
                                converted_data = self._convert_audio_bytes(audio_data, sample_width)
                                if len(converted_data) > 0:
                                    audio_buffers.append(converted_data)
                        else:
                            # 如果没有找到数据块，整个块都当作音频数据处理
                            converted_data = self._convert_audio_bytes(chunk, sample_width)
                            if len(converted_data) > 0:
                                audio_buffers.append(converted_data)
                    else:
                        # 没有WAV头部，直接当作音频数据处理
                        logger.debug("第一个块没有WAV头部，直接处理为音频数据")
                        converted_data = self._convert_audio_bytes(chunk, sample_width)
                        if len(converted_data) > 0:
                            audio_buffers.append(converted_data)
                    
                    first_chunk = False
                else:
                    # 后续块直接当作音频数据处理
                    converted_data = self._convert_audio_bytes(chunk, sample_width)
                    if len(converted_data) > 0:
                        audio_buffers.append(converted_data)
            
            # 合并所有音频数据
            if audio_buffers:
                try:
                    # 确保所有数组具有一致的维度
                    processed_buffers = []
                    for buf in audio_buffers:
                        if len(buf.shape) == 1:
                            # 一维数组转二维 (samples, 1)
                            processed_buffers.append(buf.reshape(-1, 1))
                        else:
                            processed_buffers.append(buf)
                    
                    full_audio = np.vstack(processed_buffers)
                    
                    # 如果是单声道，转换为一维数组
                    if full_audio.shape[1] == 1:
                        full_audio = full_audio.flatten()
                    
                    logger.debug(f"播放音频数据，总长度: {len(full_audio)} 采样点, 采样率: {sample_rate}")
                    # 播放完整音频
                    sd.play(full_audio, sample_rate)
                    sd.wait()  # 等待播放完成
                    logger.debug("音频播放完成")
                except Exception as e:
                    logger.error(f"合并或播放音频时出错: {e}")
            else:
                logger.debug("没有有效的音频数据可供播放")
                
        except Exception as e:
            logger.error(f"播放音频时出错: {e}")
    
    def play_file(self, file_path: str):
        """
        播放本地WAV文件
        
        Args:
            file_path: WAV文件路径
        """
        if not AUDIO_AVAILABLE:
            logger.error("错误: 音频播放不可用")
            return
            
        try:
            # 使用soundfile读取音频文件
            data, sample_rate = sf.read(file_path)
            logger.debug(f"播放文件: {file_path}, 采样率: {sample_rate}, 长度: {len(data)}")
            
            # 播放音频
            sd.play(data, sample_rate)
            sd.wait()  # 等待播放完成
            logger.debug("文件播放完成")
            
        except Exception as e:
            logger.error(f"播放文件时出错: {e}")


