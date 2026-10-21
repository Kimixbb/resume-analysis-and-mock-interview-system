"""OpenAI-compatible LLM client: JSON in, Pydantic model out."""

import json
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.errors import LLMOutputInvalid, LLMUpstreamError

T = TypeVar("T", bound=BaseModel)

# 调用OpenAI的API，返回的是JSON格式的输出
def model_json(
    system: str, #这个是全局设定，一般用来设定模型角色
    user: str, #这个是用户输入，模型会根据这个输入生成输出
    schema: type[T], # 规定我们希望得到的json类，统一用json格式来交流数据
    temperature: float = 0.2, # 这个参数是随机性，0-1，0.2希望它的输出更加稳定一些
) -> T:
    url = settings.openai_base_url + "/chat/completions"
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    for attempt in range(2):
        try:
            resp = httpx.post(
                url,
                headers={"Authorization": f"Bearer {settings.openai_api_key}"}, #手动请求头
                json={
                    "model": settings.openai_model,
                    "messages": messages,
                    "temperature": temperature,
                },
                timeout=settings.llm_timeout,
            )
            resp.raise_for_status() # 自带方法，如果响应状态码不是200，会抛出异常
            '''
            根据/chat/completions"定义的规范，大模型返回的回答大概长这样
            {
              "choices": [
                {
                  "message": {
                    "role": "assistant",
                    "content": "模型输出的文字"
                  },
                  "finish_reason": "stop"
                }
              ]
            }
            '''
            text = resp.json()["choices"][0]["message"]["content"]
            # 检查返回的文本是否为空
            if not isinstance(text, str) or not text.strip():
                raise ValueError("字符串为空")
            # 提取json部分
            start, end = text.find("{"), text.rfind("}")
            if start == -1 or end <= start:
                raise ValueError("没有找到JSON对象")
            return schema.model_validate(json.loads(text[start : end + 1])) #返回校验转化后的对象

        except httpx.HTTPError as exc:
            raise LLMUpstreamError("模型服务请求失败") from exc
        except (ValueError, KeyError, IndexError, TypeError, ValidationError) as exc:
            if attempt == 1:
                raise LLMOutputInvalid("模型输出不符合约定") from exc
            messages.append(
                {
                    "role": "user",
                    "content": "只输出一个 JSON 对象，不要其他辅助文本，不要解释。",
                }
            ) # 输出不符合规定就加上这条用户信息，强制定义规范

    raise LLMOutputInvalid("模型输出不符合约定") #如果两轮都没return直接异常
