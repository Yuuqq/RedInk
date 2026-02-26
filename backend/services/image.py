"""图片生成服务"""
import logging
import os
import re
import uuid
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Any, Generator, List, Optional, Tuple
from backend.config import Config
from backend.generators.factory import ImageGeneratorFactory
from backend.utils.image_compressor import compress_image

logger = logging.getLogger(__name__)


class ImageService:
    """图片生成服务类"""

    _TASK_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")

    # 并发配置
    MAX_CONCURRENT = 15  # 最大并发数
    AUTO_RETRY_COUNT = 1  # 不自动重试，超时后让用户手动重试

    # 任务状态保留时间（秒），防止 _task_states 无限增长
    TASK_STATE_TTL_SECONDS = int(os.environ.get("REDINK_TASK_STATE_TTL_SECONDS", str(6 * 60 * 60)))  # 6h

    def __init__(self, provider_name: str = None):
        """
        初始化图片生成服务

        Args:
            provider_name: 服务商名称，如果为None则使用配置文件中的激活服务商
        """
        logger.debug("初始化 ImageService...")

        # 获取服务商配置
        if provider_name is None:
            provider_name = Config.get_active_image_provider()

        logger.info(f"使用图片服务商: {provider_name}")
        provider_config = Config.get_image_provider_config(provider_name)

        # 创建生成器实例
        provider_type = provider_config.get('type', provider_name)
        logger.debug(f"创建生成器: type={provider_type}")
        self.generator = ImageGeneratorFactory.create(provider_type, provider_config)

        # 保存配置信息
        self.provider_name = provider_name
        self.provider_config = provider_config

        # 检查是否启用短 prompt 模式
        self.use_short_prompt = provider_config.get('short_prompt', False)

        # 加载提示词模板
        self.prompt_template = self._load_prompt_template()
        self.prompt_template_short = self._load_prompt_template(short=True)

        # 历史记录根目录
        self.history_root_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "history"
        )
        os.makedirs(self.history_root_dir, exist_ok=True)

        # 存储任务状态（用于重试）
        self._task_states: Dict[str, Dict] = {}
        self._task_states_lock = threading.Lock()

        logger.info(f"ImageService 初始化完成: provider={provider_name}, type={provider_type}")

    @classmethod
    def _is_safe_task_id(cls, task_id: str) -> bool:
        return bool(cls._TASK_ID_RE.fullmatch(str(task_id) or ""))

    def _get_task_dir(self, task_id: str, *, create: bool = False) -> str:
        """
        Return a safe task directory path inside history_root_dir.

        Prevent path traversal and refuse symlinks.
        """
        task_id = str(task_id) if task_id is not None else ""
        if not self._is_safe_task_id(task_id):
            raise ValueError("参数错误：task_id 不安全")

        base = Path(self.history_root_dir).resolve()
        raw = base / task_id
        try:
            resolved = raw.resolve()
            resolved.relative_to(base)
        except Exception as e:
            raise ValueError("参数错误：task_id 不安全") from e

        try:
            if raw.exists() and raw.is_symlink():
                raise ValueError("参数错误：任务目录不安全（符号链接）")
        except ValueError:
            raise
        except Exception as e:
            raise ValueError("参数错误：任务目录不安全") from e

        if create:
            os.makedirs(str(resolved), exist_ok=True)

        return str(resolved)

    def _touch_task_state(self, task_id: str):
        """更新任务状态最后访问时间"""
        with self._task_states_lock:
            state = self._task_states.get(task_id)
            if state is not None:
                state["updated_at"] = time.time()

    def _cleanup_expired_task_states(self):
        """清理过期的任务状态，释放内存"""
        ttl = self.TASK_STATE_TTL_SECONDS
        if ttl <= 0:
            return

        now = time.time()
        removed = 0
        with self._task_states_lock:
            for task_id in list(self._task_states.keys()):
                state = self._task_states.get(task_id) or {}
                ts = state.get("updated_at") or state.get("created_at") or now
                if now - ts > ttl:
                    del self._task_states[task_id]
                    removed += 1

        if removed:
            logger.info(f"清理过期任务状态: removed={removed}, ttl={ttl}s")

    def _is_task_cancelled(self, task_id: str) -> bool:
        with self._task_states_lock:
            state = self._task_states.get(task_id)
            return bool(state and state.get("cancelled"))

    def cancel_task(self, task_id: str) -> bool:
        """Mark a task as cancelled so any running generation can stop early."""
        self._cleanup_expired_task_states()
        with self._task_states_lock:
            state = self._task_states.get(task_id)
            if state is None:
                return False
            state["cancelled"] = True
            state["updated_at"] = time.time()
            return True

    def _load_prompt_template(self, short: bool = False) -> str:
        """加载 Prompt 模板"""
        filename = "image_prompt_short.txt" if short else "image_prompt.txt"
        prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "prompts",
            filename
        )
        if not os.path.exists(prompt_path):
            # 如果短模板不存在，返回空字符串
            return ""
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()

    def _save_image(self, image_data: bytes, filename: str, task_dir: str) -> str:
        """
        保存图片到本地，同时生成缩略图

        Args:
            image_data: 图片二进制数据
            filename: 文件名
            task_dir: 任务目录

        Returns:
            保存的文件路径
        """
        if not task_dir:
            raise ValueError("任务目录未设置")

        # 保存原图
        filepath = os.path.join(task_dir, filename)
        with open(filepath, "wb") as f:
            f.write(image_data)

        # 生成缩略图（50KB左右）
        thumbnail_data = compress_image(image_data, max_size_kb=50)
        thumbnail_filename = f"thumb_{filename}"
        thumbnail_path = os.path.join(task_dir, thumbnail_filename)
        with open(thumbnail_path, "wb") as f:
            f.write(thumbnail_data)

        return filepath

    def _generate_single_image(
        self,
        page: Dict,
        task_id: str,
        task_dir: str,
        reference_image: Optional[bytes] = None,
        retry_count: int = 0,
        full_outline: str = "",
        user_images: Optional[List[bytes]] = None,
        user_topic: str = "",
        style_hint: str = "",
    ) -> Tuple[int, bool, Optional[str], Optional[str]]:
        """
        生成单张图片（带自动重试）

        Args:
            page: 页面数据
            task_id: 任务ID
            task_dir: 任务目录
            reference_image: 参考图片（封面图）
            retry_count: 当前重试次数
            full_outline: 完整的大纲文本
            user_images: 用户上传的参考图片列表
            user_topic: 用户原始输入

        Returns:
            (index, success, filename, error_message)
        """
        index = page["index"]
        page_type = page["type"]
        page_content = page["content"]

        try:
            logger.debug(f"生成图片 [{index}]: type={page_type}")

            # 根据配置选择模板（短 prompt 或完整 prompt）
            if self.use_short_prompt and self.prompt_template_short:
                # 短 prompt 模式：只包含页面类型和内容
                prompt = self.prompt_template_short.format(
                    page_content=page_content,
                    page_type=page_type
                )
                logger.debug(f"  使用短 prompt 模式 ({len(prompt)} 字符)")
            else:
                # 完整 prompt 模式：包含大纲和用户需求
                prompt = self.prompt_template.format(
                    page_content=page_content,
                    page_type=page_type,
                    full_outline=full_outline,
                    user_topic=user_topic if user_topic else "未提供"
                )

            if style_hint:
                prompt = f"{prompt}\n\n风格偏好：\n{style_hint}\n"

            # 调用生成器生成图片
            if self.provider_config.get('type') == 'google_genai':
                logger.debug(f"  使用 Google GenAI 生成器")
                image_data = self.generator.generate_image(
                    prompt=prompt,
                    aspect_ratio=self.provider_config.get('default_aspect_ratio', '3:4'),
                    temperature=self.provider_config.get('temperature', 1.0),
                    model=self.provider_config.get('model', 'gemini-3-pro-image-preview'),
                    reference_image=reference_image,
                )
            elif self.provider_config.get('type') == 'image_api':
                logger.debug(f"  使用 Image API 生成器")
                # Image API 支持多张参考图片
                # 组合参考图片：用户上传的图片 + 封面图
                reference_images = []
                if user_images:
                    reference_images.extend(user_images)
                if reference_image:
                    reference_images.append(reference_image)

                image_data = self.generator.generate_image(
                    prompt=prompt,
                    aspect_ratio=self.provider_config.get('default_aspect_ratio', '3:4'),
                    temperature=self.provider_config.get('temperature', 1.0),
                    model=self.provider_config.get('model', 'nano-banana-2'),
                    reference_images=reference_images if reference_images else None,
                )
            else:
                logger.debug(f"  使用 OpenAI 兼容生成器")
                image_data = self.generator.generate_image(
                    prompt=prompt,
                    size=self.provider_config.get('default_size', '1024x1024'),
                    model=self.provider_config.get('model'),
                    quality=self.provider_config.get('quality', 'standard'),
                )

            # 保存图片
            filename = f"{index}.png"
            self._save_image(image_data, filename, task_dir)
            logger.info(f"✅ 图片 [{index}] 生成成功: {filename}")

            return (index, True, filename, None)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ 图片 [{index}] 生成失败: {error_msg[:200]}")
            return (index, False, None, error_msg)

    def generate_images(
        self,
        pages: list,
        task_id: str = None,
        full_outline: str = "",
        user_images: Optional[List[bytes]] = None,
        user_topic: str = "",
        style_hint: str = "",
    ) -> Generator[Dict[str, Any], None, None]:
        """
        生成图片（生成器，支持 SSE 流式返回）
        优化版本：先生成封面，然后并发生成其他页面

        Args:
            pages: 页面列表
            task_id: 任务 ID（可选）
            full_outline: 完整的大纲文本（用于保持风格一致）
            user_images: 用户上传的参考图片列表（可选）
            user_topic: 用户原始输入（用于保持意图一致）

        Yields:
            进度事件字典
        """
        self._cleanup_expired_task_states()

        if not task_id:
            task_id = f"task_{uuid.uuid4().hex[:8]}"
        else:
            task_id = str(task_id)
            if not self._is_safe_task_id(task_id):
                raise ValueError("参数错误：task_id 不安全")

        logger.info(f"开始图片生成任务: task_id={task_id}, pages={len(pages)}")

        # 创建任务专属目录
        task_dir = self._get_task_dir(task_id, create=True)
        logger.debug(f"任务目录: {task_dir}")

        total = len(pages)
        generated_images = []
        failed_pages = []
        cover_image_data = None

        # 压缩用户上传的参考图到200KB以内（减少内存和传输开销）
        compressed_user_images = None
        if user_images:
            compressed_user_images = [compress_image(img, max_size_kb=200) for img in user_images]

        # 初始化/更新任务状态（支持断点续生成）
        now = time.time()
        with self._task_states_lock:
            state = self._task_states.get(task_id)
            if state is None:
                self._task_states[task_id] = {
                    "created_at": now,
                    "updated_at": now,
                    "pages": pages,
                    "generated": {},
                    "failed": {},
                    "cover_image": None,
                    "full_outline": full_outline,
                    "user_images": compressed_user_images,
                    "user_topic": user_topic,
                    "style_hint": style_hint,
                    "cancelled": False,
                }
            else:
                state.setdefault("created_at", now)
                state.setdefault("generated", {})
                state.setdefault("failed", {})
                state.setdefault("cover_image", None)
                state["pages"] = pages
                state["full_outline"] = full_outline
                if compressed_user_images is not None:
                    state["user_images"] = compressed_user_images
                state["user_topic"] = user_topic or state.get("user_topic") or ""
                state["style_hint"] = style_hint or state.get("style_hint") or ""
                # A new generate request clears cancellation, allowing resume.
                state["cancelled"] = False
                state["updated_at"] = now

        # 扫描磁盘上已生成的图片（用于刷新/断点续生成）
        expected_indices = set()
        for p in pages:
            if not isinstance(p, dict):
                continue
            try:
                expected_indices.add(int(p.get("index", -1)))
            except Exception:
                continue

        existing_generated: Dict[int, str] = {}
        try:
            for filename in os.listdir(task_dir):
                if filename.startswith("thumb_"):
                    continue
                name, ext = os.path.splitext(filename)
                if ext.lower() not in (".png", ".jpg", ".jpeg"):
                    continue
                if not name.isdigit():
                    continue
                idx = int(name)
                if expected_indices and idx not in expected_indices:
                    continue
                existing_generated[idx] = filename
        except Exception:
            existing_generated = {}

        if existing_generated:
            with self._task_states_lock:
                state = self._task_states.get(task_id) or {}
                generated_map = state.get("generated", {}) or {}
                failed_map = state.get("failed", {}) or {}
                for idx, fname in existing_generated.items():
                    generated_map[idx] = fname
                    if idx in failed_map:
                        del failed_map[idx]
                state["generated"] = generated_map
                state["failed"] = failed_map
                state["updated_at"] = time.time()

            # 用于进度计数（只关心数量，不关心顺序）
            generated_images = list(existing_generated.values())

            # 主动回放 complete 事件，便于前端刷新后恢复 UI
            for idx in sorted(existing_generated.keys()):
                fname = existing_generated[idx]
                yield {
                    "event": "complete",
                    "data": {
                        "index": idx,
                        "status": "done",
                        "image_url": f"/api/images/{task_id}/{fname}",
                        "phase": "resume"
                    }
                }

        cancelled = False

        # ==================== 第一阶段：生成封面 ====================
        cover_page = None
        other_pages = []

        for page in pages:
            if page["type"] == "cover":
                cover_page = page
            else:
                other_pages.append(page)

        # 如果没有封面，使用第一页作为封面
        if cover_page is None and len(pages) > 0:
            cover_page = pages[0]
            other_pages = pages[1:]

        # 断点续生成：跳过已存在的页面文件
        if existing_generated and other_pages:
            remaining = []
            for page in other_pages:
                if not isinstance(page, dict):
                    continue
                try:
                    idx = int(page.get("index", -1))
                except Exception:
                    idx = -1
                if idx in existing_generated:
                    continue
                remaining.append(page)
            other_pages = remaining

        if cover_page:
            try:
                cover_index = int(cover_page.get("index", -1))
            except Exception:
                cover_index = -1

            existing_cover = existing_generated.get(cover_index) if cover_index >= 0 else None

            if self._is_task_cancelled(task_id):
                cancelled = True
            elif existing_cover:
                # 断点续：封面已存在，直接读取作为参考
                try:
                    cover_path = os.path.join(task_dir, existing_cover)
                    with open(cover_path, "rb") as f:
                        cover_image_data = f.read()
                    cover_image_data = compress_image(cover_image_data, max_size_kb=200)
                    with self._task_states_lock:
                        if task_id in self._task_states:
                            self._task_states[task_id]["cover_image"] = cover_image_data
                            self._task_states[task_id]["updated_at"] = time.time()
                except Exception as e:
                    logger.warning(f"读取已有封面失败: task_id={task_id}, file={existing_cover}, err={e}")
            else:
                # 发送封面生成进度
                yield {
                    "event": "progress",
                    "data": {
                        "index": cover_page["index"],
                        "status": "generating",
                        "message": "正在生成封面...",
                        "current": len(generated_images) + 1,
                        "total": total,
                        "phase": "cover"
                    }
                }

                # 生成封面（使用用户上传的图片作为参考）
                index, success, filename, error = self._generate_single_image(
                    cover_page, task_id, task_dir, reference_image=None, full_outline=full_outline,
                    user_images=compressed_user_images, user_topic=user_topic, style_hint=style_hint
                )

                if success:
                    generated_images.append(filename)
                    with self._task_states_lock:
                        self._task_states[task_id]["generated"][index] = filename
                        self._task_states[task_id]["updated_at"] = time.time()

                    # 读取封面图片作为参考，并立即压缩到200KB以内
                    cover_path = os.path.join(task_dir, filename)
                    with open(cover_path, "rb") as f:
                        cover_image_data = f.read()

                    # 压缩封面图（减少内存占用和后续传输开销）
                    cover_image_data = compress_image(cover_image_data, max_size_kb=200)
                    with self._task_states_lock:
                        self._task_states[task_id]["cover_image"] = cover_image_data
                        self._task_states[task_id]["updated_at"] = time.time()

                    yield {
                        "event": "complete",
                        "data": {
                            "index": index,
                            "status": "done",
                            "image_url": f"/api/images/{task_id}/{filename}",
                            "phase": "cover"
                        }
                    }
                else:
                    failed_pages.append(cover_page)
                    with self._task_states_lock:
                        self._task_states[task_id]["failed"][index] = error
                        self._task_states[task_id]["updated_at"] = time.time()

                    yield {
                        "event": "error",
                        "data": {
                            "index": index,
                            "status": "error",
                            "message": error,
                            "retryable": True,
                            "phase": "cover"
                        }
                    }

        # ==================== 第二阶段：生成其他页面 ====================
        if other_pages and not cancelled:
            # 检查是否启用高并发模式
            high_concurrency = self.provider_config.get('high_concurrency', False)

            if high_concurrency:
                # 高并发模式：并行生成
                yield {
                    "event": "progress",
                    "data": {
                        "status": "batch_start",
                        "message": f"开始并发生成 {len(other_pages)} 页内容...",
                        "current": len(generated_images),
                        "total": total,
                        "phase": "content"
                    }
                }

                # 使用线程池并发生成
                with ThreadPoolExecutor(max_workers=self.MAX_CONCURRENT) as executor:
                    # 提交任务（支持取消：尽量不提交剩余页面）
                    future_to_page = {}
                    for page in other_pages:
                        if self._is_task_cancelled(task_id):
                            cancelled = True
                            break

                        future = executor.submit(
                            self._generate_single_image,
                            page,
                            task_id,
                            task_dir,
                            cover_image_data,  # 使用封面作为参考
                            0,  # retry_count
                            full_outline,  # 传入完整大纲
                            compressed_user_images,  # 用户上传的参考图片（已压缩）
                            user_topic,  # 用户原始输入
                            style_hint,  # 风格偏好
                        )
                        future_to_page[future] = page

                    # 发送每个页面的进度（仅对已提交的页面）
                    for page in future_to_page.values():
                        yield {
                            "event": "progress",
                            "data": {
                                "index": page["index"],
                                "status": "generating",
                                "current": len(generated_images) + 1,
                                "total": total,
                                "phase": "content"
                            }
                        }

                    # 收集结果
                    for future in as_completed(future_to_page):
                        if self._is_task_cancelled(task_id):
                            cancelled = True
                            # 尽量取消还未开始的任务
                            for f in future_to_page.keys():
                                try:
                                    f.cancel()
                                except Exception:
                                    pass
                            break

                        page = future_to_page[future]
                        try:
                            index, success, filename, error = future.result()

                            if success:
                                generated_images.append(filename)
                                with self._task_states_lock:
                                    self._task_states[task_id]["generated"][index] = filename
                                    self._task_states[task_id]["updated_at"] = time.time()

                                yield {
                                    "event": "complete",
                                    "data": {
                                        "index": index,
                                        "status": "done",
                                        "image_url": f"/api/images/{task_id}/{filename}",
                                        "phase": "content"
                                    }
                                }
                            else:
                                failed_pages.append(page)
                                with self._task_states_lock:
                                    self._task_states[task_id]["failed"][index] = error
                                    self._task_states[task_id]["updated_at"] = time.time()

                                yield {
                                    "event": "error",
                                    "data": {
                                        "index": index,
                                        "status": "error",
                                        "message": error,
                                        "retryable": True,
                                        "phase": "content"
                                    }
                                }

                        except Exception as e:
                            failed_pages.append(page)
                            error_msg = str(e)
                            with self._task_states_lock:
                                self._task_states[task_id]["failed"][page["index"]] = error_msg
                                self._task_states[task_id]["updated_at"] = time.time()

                            yield {
                                "event": "error",
                                "data": {
                                    "index": page["index"],
                                    "status": "error",
                                    "message": error_msg,
                                    "retryable": True,
                                    "phase": "content"
                                }
                            }
            else:
                # 顺序模式：逐个生成
                yield {
                    "event": "progress",
                    "data": {
                        "status": "batch_start",
                        "message": f"开始顺序生成 {len(other_pages)} 页内容...",
                        "current": len(generated_images),
                        "total": total,
                        "phase": "content"
                    }
                }

                for page in other_pages:
                    if self._is_task_cancelled(task_id):
                        cancelled = True
                        break

                    # 发送生成进度
                    yield {
                        "event": "progress",
                        "data": {
                            "index": page["index"],
                            "status": "generating",
                            "current": len(generated_images) + 1,
                            "total": total,
                            "phase": "content"
                        }
                    }

                    # 生成单张图片
                    index, success, filename, error = self._generate_single_image(
                        page,
                        task_id,
                        task_dir,
                        cover_image_data,
                        0,
                        full_outline,
                        compressed_user_images,
                        user_topic,
                        style_hint,
                    )

                    if success:
                        generated_images.append(filename)
                        with self._task_states_lock:
                            self._task_states[task_id]["generated"][index] = filename
                            self._task_states[task_id]["updated_at"] = time.time()

                        yield {
                            "event": "complete",
                            "data": {
                                "index": index,
                                "status": "done",
                                "image_url": f"/api/images/{task_id}/{filename}",
                                "phase": "content"
                            }
                        }
                    else:
                        failed_pages.append(page)
                        with self._task_states_lock:
                            self._task_states[task_id]["failed"][index] = error
                            self._task_states[task_id]["updated_at"] = time.time()

                        yield {
                            "event": "error",
                            "data": {
                                "index": index,
                                "status": "error",
                                "message": error,
                                "retryable": True,
                                "phase": "content"
                            }
                        }

        # ==================== 完成 ====================
        # 构建 index 对齐的图片列表，避免并发完成顺序导致前端/历史记录错位
        max_index = -1
        try:
            max_index = max(int(p.get("index", -1)) for p in pages if isinstance(p, dict))
        except Exception:
            max_index = -1

        expected_len = max(total, (max_index + 1) if max_index >= 0 else total)

        images_by_index: List[Optional[str]] = [None] * expected_len
        with self._task_states_lock:
            generated_map = dict((self._task_states.get(task_id) or {}).get("generated", {}) or {})

        for idx, fname in generated_map.items():
            try:
                i = int(idx)
            except Exception:
                continue
            if 0 <= i < expected_len:
                images_by_index[i] = fname

        completed_count = sum(1 for x in images_by_index if x)
        cancelled_final = cancelled or self._is_task_cancelled(task_id)

        expected_list = sorted(expected_indices) if expected_indices else list(range(total))
        remaining_indices: List[int] = []
        for i in expected_list:
            if i < 0:
                continue
            if i >= len(images_by_index) or images_by_index[i] is None:
                remaining_indices.append(i)

        failed_indices = []
        for p in failed_pages:
            if isinstance(p, dict) and "index" in p:
                failed_indices.append(p["index"])

        yield {
            "event": "finish",
            "data": {
                "success": (not cancelled_final) and (len(remaining_indices) == 0),
                "task_id": task_id,
                "images": images_by_index,
                "total": total,
                "completed": completed_count,
                "failed": len(remaining_indices),
                "failed_indices": failed_indices,
                "cancelled": cancelled_final,
                "remaining_indices": remaining_indices,
            }
        }

    def retry_single_image(
        self,
        task_id: str,
        page: Dict,
        use_reference: bool = True,
        full_outline: str = "",
        user_topic: str = "",
        style_hint: str = "",
    ) -> Dict[str, Any]:
        """
        重试生成单张图片

        Args:
            task_id: 任务ID
            page: 页面数据
            use_reference: 是否使用封面作为参考
            full_outline: 完整大纲文本（从前端传入）
            user_topic: 用户原始输入（从前端传入）

        Returns:
            生成结果
        """
        self._cleanup_expired_task_states()

        task_dir = self._get_task_dir(task_id, create=True)

        reference_image = None
        user_images = None

        # 首先尝试从任务状态中获取上下文
        with self._task_states_lock:
            task_state = self._task_states.get(task_id)

        if task_state:
            if use_reference:
                reference_image = task_state.get("cover_image")
            # 如果没有传入上下文，则使用任务状态中的
            if not full_outline:
                full_outline = task_state.get("full_outline", "")
            if not user_topic:
                user_topic = task_state.get("user_topic", "")
            if not style_hint:
                style_hint = task_state.get("style_hint", "")
            user_images = task_state.get("user_images")
            self._touch_task_state(task_id)

        # 如果任务状态中没有封面图，尝试从文件系统加载
        if use_reference and reference_image is None:
            cover_path = os.path.join(task_dir, "0.png")
            if os.path.exists(cover_path):
                with open(cover_path, "rb") as f:
                    cover_data = f.read()
                # 压缩封面图到 200KB
                reference_image = compress_image(cover_data, max_size_kb=200)

        index, success, filename, error = self._generate_single_image(
            page,
            task_id,
            task_dir,
            reference_image,
            0,
            full_outline,
            user_images,
            user_topic,
            style_hint,
        )

        if success:
            with self._task_states_lock:
                if task_id in self._task_states:
                    self._task_states[task_id]["generated"][index] = filename
                    if index in self._task_states[task_id]["failed"]:
                        del self._task_states[task_id]["failed"][index]
                    self._task_states[task_id]["updated_at"] = time.time()

            return {
                "success": True,
                "index": index,
                "image_url": f"/api/images/{task_id}/{filename}"
            }
        else:
            return {
                "success": False,
                "index": index,
                "error": error,
                "retryable": True
            }

    def retry_failed_images(
        self,
        task_id: str,
        pages: List[Dict]
    ) -> Generator[Dict[str, Any], None, None]:
        """
        批量重试失败的图片

        Args:
            task_id: 任务ID
            pages: 需要重试的页面列表

        Yields:
            进度事件
        """
        self._cleanup_expired_task_states()

        # 获取参考图/上下文
        reference_image = None
        user_images = None
        cached_user_topic = ""
        full_outline = ""
        style_hint = ""
        with self._task_states_lock:
            task_state = self._task_states.get(task_id)
        if task_state:
            reference_image = task_state.get("cover_image")
            user_images = task_state.get("user_images")
            cached_user_topic = task_state.get("user_topic", "")
            full_outline = task_state.get("full_outline", "")
            style_hint = task_state.get("style_hint", "")
            self._touch_task_state(task_id)

        total = len(pages)
        success_count = 0
        failed_count = 0

        yield {
            "event": "retry_start",
            "data": {
                "total": total,
                "message": f"开始重试 {total} 张失败的图片"
            }
        }

        # 并发重试
        with ThreadPoolExecutor(max_workers=self.MAX_CONCURRENT) as executor:
            task_dir = self._get_task_dir(task_id, create=True)
            future_to_page = {
                executor.submit(
                    self._generate_single_image,
                    page,
                    task_id,
                    task_dir,
                    reference_image,
                    0,  # retry_count
                    full_outline,  # 传入完整大纲
                    user_images,
                    cached_user_topic,
                    style_hint,  # 风格偏好
                ): page
                for page in pages
            }

            for future in as_completed(future_to_page):
                page = future_to_page[future]
                try:
                    index, success, filename, error = future.result()

                    if success:
                        success_count += 1
                        with self._task_states_lock:
                            if task_id in self._task_states:
                                self._task_states[task_id]["generated"][index] = filename
                                if index in self._task_states[task_id]["failed"]:
                                    del self._task_states[task_id]["failed"][index]
                                self._task_states[task_id]["updated_at"] = time.time()

                        yield {
                            "event": "complete",
                            "data": {
                                "index": index,
                                "status": "done",
                                "image_url": f"/api/images/{task_id}/{filename}"
                            }
                        }
                    else:
                        failed_count += 1
                        yield {
                            "event": "error",
                            "data": {
                                "index": index,
                                "status": "error",
                                "message": error,
                                "retryable": True
                            }
                        }

                except Exception as e:
                    failed_count += 1
                    yield {
                        "event": "error",
                        "data": {
                            "index": page["index"],
                            "status": "error",
                            "message": str(e),
                            "retryable": True
                        }
                    }

        yield {
            "event": "retry_finish",
            "data": {
                "success": failed_count == 0,
                "total": total,
                "completed": success_count,
                "failed": failed_count
            }
        }

    def regenerate_image(
        self,
        task_id: str,
        page: Dict,
        use_reference: bool = True,
        full_outline: str = "",
        user_topic: str = "",
        style_hint: str = "",
    ) -> Dict[str, Any]:
        """
        重新生成图片（用户手动触发，即使成功的也可以重新生成）

        Args:
            task_id: 任务ID
            page: 页面数据
            use_reference: 是否使用封面作为参考
            full_outline: 完整大纲文本
            user_topic: 用户原始输入

        Returns:
            生成结果
        """
        return self.retry_single_image(
            task_id, page, use_reference,
            full_outline=full_outline,
            user_topic=user_topic,
            style_hint=style_hint,
        )

    def get_image_path(self, task_id: str, filename: str) -> str:
        """
        获取图片完整路径

        Args:
            task_id: 任务ID
            filename: 文件名

        Returns:
            完整路径
        """
        task_dir = self._get_task_dir(task_id, create=False)
        return os.path.join(task_dir, filename)

    def get_task_state(self, task_id: str) -> Optional[Dict]:
        """获取任务状态"""
        self._cleanup_expired_task_states()
        with self._task_states_lock:
            state = self._task_states.get(task_id)
        if state:
            self._touch_task_state(task_id)
        return state

    def cleanup_task(self, task_id: str):
        """清理任务状态（释放内存）"""
        with self._task_states_lock:
            if task_id in self._task_states:
                del self._task_states[task_id]

    def list_tasks(self) -> List[Dict[str, Any]]:
        """列出内存中仍保留的任务状态（不包含大字段）"""
        self._cleanup_expired_task_states()
        with self._task_states_lock:
            items = list(self._task_states.items())

        tasks: List[Dict[str, Any]] = []
        for task_id, state in items:
            generated = state.get("generated", {}) or {}
            failed = state.get("failed", {}) or {}
            tasks.append({
                "task_id": task_id,
                "created_at": state.get("created_at"),
                "updated_at": state.get("updated_at"),
                "generated_count": len(generated),
                "failed_count": len(failed),
                "has_cover": state.get("cover_image") is not None,
            })

        tasks.sort(key=lambda x: (x.get("updated_at") or 0), reverse=True)
        return tasks


# 全局服务实例
_service_instance = None
_service_lock = threading.Lock()

def get_image_service() -> ImageService:
    """获取全局图片生成服务实例"""
    global _service_instance
    if _service_instance is None:
        with _service_lock:
            if _service_instance is None:
                _service_instance = ImageService()
    return _service_instance

def reset_image_service():
    """重置全局服务实例（配置更新后调用）"""
    global _service_instance
    with _service_lock:
        _service_instance = None
