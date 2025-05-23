# -*- coding: utf-8 -*-
# @Time: 2023/11/4 20:00 
# @FileName: JoinRequest.py
# @Software: PyCharm
# @GitHub: KimmyXYC
import asyncio
from loguru import logger
from telebot import types
from utils.LogChannel import LogChannel
from app.PollButton import PollButton


class JoinRequest:
    def __init__(self, chat_id, user_id, bot_id, log_channel_id):
        self.chat_id = chat_id
        self.user_id = user_id
        self.finished = False

        self.log_channel_id = log_channel_id

        self.bot_id = bot_id
        self.bot_member = None

        self.request = None
        self.user_message = None
        self.notice_message = None
        self.polling = None
        self.anonymous_vote = True

        self.user_mention = None

        self.LogChannel = None
        self.PollButton = None

    def check_up_status(self):
        return self.finished

    def get_poll_result(self, message):
        if self.PollButton is None:
            return None
        return (f"<b>{self.request.chat.title}</b>\n"
                f"Join request from {self.user_mention}\n\n"
                f"{self.PollButton.get_result(message.from_user.id, self.anonymous_vote)}")

    async def handle_join_request(self, bot, request: types.ChatJoinRequest, db):
        self.LogChannel = LogChannel(bot, self.log_channel_id)
        self.request = request
        self.bot_member = await bot.get_chat_member(self.chat_id, self.bot_id)

        if request.from_user.username is not None:
            self.user_mention = f'@{request.from_user.username}'
        else:
            self.user_mention = f'<a href="tg://user?id={self.user_id}">{request.from_user.first_name}'
            if request.from_user.last_name is not None:
                self.user_mention += f" {request.from_user.last_name}</a>"
            else:
                self.user_mention += "</a>"

        # Log
        logger.info(f"New join request from {request.from_user.first_name}(ID: {self.user_id}) in {self.chat_id}")
        await self.LogChannel.create_log(request, "JoinRequest")

        chat_dict = db.get(str(self.chat_id))
        if chat_dict is None:
            chat_dict = {}
        status_pin_msg = chat_dict.get("pin_msg", False)
        vote_time = chat_dict.get("vote_time", 600)
        advanced_vote = chat_dict.get("advanced_vote", False)
        self.anonymous_vote = chat_dict.get("anonymous_vote", True)

        # Time format
        minutes = vote_time // 60
        seconds = vote_time % 60
        cn_parts = []
        en_parts = []
        if minutes > 0:
            cn_parts.append(f"{minutes}分钟")
            en_parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        if seconds > 0:
            cn_parts.append(f"{seconds}秒")
            en_parts.append(f"{seconds} second{'s' if seconds > 1 else ''}")
        _cn_time = ''.join(cn_parts) if cn_parts else "0秒"
        _en_time = ' and '.join(en_parts) if en_parts else "0 seconds"

        # Send message to user
        _zh_info = f"您正在申请加入「{request.chat.title}」，结果将于 {_cn_time} 后告知您。"
        _en_info = f"You are applying to join 「{request.chat.title}」. " \
                   f"The result will be communicated to you in {_en_time}."
        try:
            self.user_message = await bot.send_message(
                self.user_id,
                f"{_zh_info}\n{_en_info}",
            )
        except Exception as e:
            logger.error(f"Send message to User_id:{self.user_id}: {e}")

        # Buttons
        join_request_id = f"{self.chat_id}@{self.user_id}"
        keyboard = types.InlineKeyboardMarkup(row_width=3)
        approve_button = types.InlineKeyboardButton(text="Approve", callback_data=f"JR Approve {join_request_id}")
        reject_button = types.InlineKeyboardButton(text="Reject", callback_data=f"JR Reject {join_request_id}")
        ban_button = types.InlineKeyboardButton(text="Ban", callback_data=f"JR Ban {join_request_id}")
        keyboard.add(approve_button, reject_button, ban_button)

        notice_message_text = f"{self.user_mention} (ID: <code>{self.user_id}</code>) is requesting to join this group."
        if request.from_user.username is None:
            notice_message_text += f"\n\nAlternate Link: tg://user?id={self.user_id}"

        notice_message = await bot.send_message(
            self.chat_id,
            notice_message_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        self.notice_message = notice_message

        # Polling
        if advanced_vote:
            self.PollButton = PollButton(join_request_id)
            keyboard = self.PollButton.button_create()
            self.polling = await bot.send_message(
                self.chat_id,
                "Approve this user?",
                reply_markup=keyboard,
                parse_mode="HTML",
                protect_content=True,
            )
        else:
            vote_question = "Approve this user?"
            vote_options = ["Yes", "No"]
            self.polling = await bot.send_poll(
                self.chat_id,
                vote_question,
                vote_options,
                is_anonymous=self.anonymous_vote,
                allows_multiple_answers=False,
                reply_to_message_id=notice_message.message_id,
                protect_content=True,
            )

        if status_pin_msg and self.bot_member.status == 'administrator' and self.bot_member.can_pin_messages:
            await bot.pin_chat_message(
                chat_id=self.chat_id,
                message_id=self.polling.message_id,
                disable_notification=True,
            )

        await asyncio.sleep(vote_time)

        # Check if the request has been processed
        if self.finished:
            return

        if status_pin_msg and self.bot_member.status == 'administrator' and self.bot_member.can_pin_messages:
            await bot.unpin_chat_message(
                chat_id=self.chat_id,
                message_id=self.polling.message_id,
            )

        # Get vote result
        if advanced_vote:
            allow_count, deny_count = self.PollButton.stop_poll()
        else:
            vote_message = await bot.stop_poll(request.chat.id, self.polling.message_id)
            allow_count = vote_message.options[0].voter_count
            deny_count = vote_message.options[1].voter_count

        # Process the vote result
        if allow_count + deny_count == 0:
            logger.info(f"{self.user_id}: No one voted in {self.chat_id}")
            result_message = bot.reply_to(notice_message, "No one voted.")
            approve_user = False
            edit_msg = f"{self.user_mention} (ID: <code>{self.user_id}</code>): No one voted."
            user_reply_msg = "无人投票，请稍后尝试重新申请。\nNo one voted. Please request again later."
        elif allow_count > deny_count:
            logger.info(f"{self.user_id}: Approved in {self.chat_id}")
            result_message = await bot.reply_to(notice_message, "Approved.")
            approve_user = True
            edit_msg = f"{self.user_mention} (ID: <code>{self.user_id}</code>): Approved."
            user_reply_msg = "您已获批准加入\nYou have been approved."
        elif allow_count == deny_count:
            logger.info(f"{self.user_id}: Tie in {self.chat_id}")
            result_message = await bot.reply_to(notice_message, "Tie.")
            approve_user = False
            edit_msg = f"{self.user_mention} (ID: <code>{self.user_id}</code>): Tie."
            user_reply_msg = "平票，请稍后尝试重新申请。\nTie. Please request again later."
        else:
            logger.info(f"{self.user_id}: Denied in {self.chat_id}")
            result_message = await bot.reply_to(notice_message, "Denied.")
            approve_user = False
            edit_msg = f"{self.user_mention} (ID: <code>{self.user_id}</code>): Denied."
            user_reply_msg = "您的申请已被拒绝。\nYou have been denied."

        # Process the request
        if self.PollButton is not None:
            await bot.edit_message_text(f"Poll has ended\nAllow : Deny = {allow_count} : {deny_count}",
                                        chat_id=self.chat_id, message_id=self.polling.message_id)
        edit_task = bot.edit_message_text(edit_msg, chat_id=self.chat_id,
                                          message_id=notice_message.message_id, parse_mode="HTML")
        reply_task = bot.reply_to(self.user_message, user_reply_msg)
        if approve_user:
            log_task = self.LogChannel.update_log("Approved", allow_count, deny_count)
            request_task = bot.approve_chat_join_request(request.chat.id, request.from_user.id)
        else:
            log_task = self.LogChannel.update_log("Denied", allow_count, deny_count)
            request_task = bot.decline_chat_join_request(request.chat.id, request.from_user.id)
        try:
            await asyncio.gather(
                edit_task,
                reply_task,
                log_task,
                request_task
            )
        except Exception as e:
            logger.error(f"An error occurred during processing: {e}")

        self.finished = True

        await asyncio.sleep(60)

        # Clean up
        await bot.delete_message(chat_id=request.chat.id, message_id=self.polling.message_id)
        await bot.delete_message(chat_id=request.chat.id, message_id=result_message.message_id)

    async def handle_button(self, bot, callback_query: types.CallbackQuery, action):
        chat_member = await bot.get_chat_member(self.chat_id, callback_query.from_user.id)

        # Check permission
        if not (chat_member.status == 'creator'):
            if not (chat_member.status == 'administrator'):
                await bot.answer_callback_query(callback_query.id, "You have no permission to do this.")
                return
            if action in ["Approve", "Reject"]:
                if not chat_member.can_invite_users:
                    await bot.answer_callback_query(callback_query.id, "You have no permission to do this.")
                    return
            elif action == "Ban":
                if not chat_member.can_restrict_members:
                    await bot.answer_callback_query(callback_query.id, "You have no permission to do this.")
                    return

        # Process the request
        if self.finished:
            await bot.answer_callback_query(callback_query.id, "This request has been processed")
            return

        admin_mention = f'<a href="tg://user?id={callback_query.from_user.id}">{callback_query.from_user.first_name}'
        if callback_query.from_user.last_name is not None:
            admin_mention += f" {callback_query.from_user.last_name}</a>"
        else:
            admin_mention += "</a>"

        if action == "Approve":
            self.finished = True
            approve_user = True
            await bot.answer_callback_query(callback_query.id, "Approved.")
            logger.info(f"{self.user_id}: Approved by {callback_query.from_user.id} in {self.chat_id}")
            await self.LogChannel.update_log_admin("Approved", admin_mention)
            edit_msg = f"{self.user_mention} (ID: <code>{self.user_id}</code>): Approved by {admin_mention}"
            reply_msg = "您已获批准加入\nYour application have been approved."
        elif action == "Reject":
            self.finished = True
            approve_user = False
            await bot.answer_callback_query(callback_query.id, "Denied.")
            logger.info(f"{self.user_id}: Denied by {callback_query.from_user.id} in {self.chat_id}")
            await self.LogChannel.update_log_admin("Denied", admin_mention)
            edit_msg = f"{self.user_mention} (ID: <code>{self.user_id}</code>): Denied by {admin_mention}"
            reply_msg = "您的申请已被拒绝。\nYour application have been denied."
        elif action == "Ban":
            if self.bot_member.status == 'administrator' and self.bot_member.can_restrict_members:
                self.finished = True
                approve_user = False
                await bot.kick_chat_member(self.chat_id, self.user_id)
                await bot.answer_callback_query(callback_query.id, "Banned.")
                logger.info(f"{self.user_id}: Banned by {callback_query.from_user.id} in {self.chat_id}")
                await self.LogChannel.update_log_admin("Banned", admin_mention)
                edit_msg = f"{self.user_mention} (ID: <code>{self.user_id}</code>): Banned by {admin_mention}"
                reply_msg = "您的申请已被拒绝。\nYour application have been denied."
            else:
                self.finished = True
                approve_user = False
                await bot.answer_callback_query(callback_query.id, "Bot has no permission to ban.")
                logger.info(f"{self.user_id}: Denied by {callback_query.from_user.id} in {self.chat_id}")
                await self.LogChannel.update_log_admin("Denied", admin_mention)
                edit_msg = f"{self.user_mention} (ID: <code>{self.user_id}</code>): Denied by {admin_mention}"
                reply_msg = "您的申请已被拒绝。\nYour application have been denied."
        else:
            await bot.answer_callback_query(callback_query.id, "Unknown action.")
            logger.error(f"Unknown action: {action}")
            return

        edit_task = bot.edit_message_text(edit_msg, chat_id=self.chat_id,
                                          message_id=self.notice_message.message_id, parse_mode="HTML")
        reply_task = bot.reply_to(self.user_message, reply_msg)
        if approve_user:
            request_task = bot.approve_chat_join_request(self.request.chat.id, self.request.from_user.id)
        else:
            request_task = bot.decline_chat_join_request(self.request.chat.id, self.request.from_user.id)
        try:
            await asyncio.gather(
                edit_task,
                reply_task,
                request_task,
            )
        except Exception as e:
            logger.error(f"An error occurred: {e}")
        if self.PollButton is not None:
            self.PollButton.stop_poll()
        else:
            try:
                bot.stop_poll(self.request.chat.id, self.polling.message_id)
            except Exception as e:
                logger.error(f"Stop poll failed: {e}")
        await bot.delete_message(chat_id=self.chat_id, message_id=self.polling.message_id)

    async def poll_button_handle(self, bot, callback_query: types.CallbackQuery):
        if self.finished:
            await bot.answer_callback_query(callback_query.id, "Poll has ended")
            return
        user_id = callback_query.from_user.id
        try:
            user_member = await bot.get_chat_member(self.chat_id, user_id)
            if user_member.status not in ['administrator', 'creator', 'member']:
                await bot.answer_callback_query(callback_query.id, "You are not in this group")
                return
        except Exception:
            await bot.answer_callback_query(callback_query.id, "You are not in this group")
            return
        await self.PollButton.user_poll_handle(bot, callback_query)
