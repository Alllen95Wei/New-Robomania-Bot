# coding=utf-8
import aiohttp
from os import getenv
from json import dump, load
from dotenv import load_dotenv


class RobowebAPI:
    # BASE_URL = "https://frc7636.dpdns.org/api/"
    load_dotenv("TOKEN.env")
    BASE_URL = getenv("ROBOWEB_API_URL")

    def __init__(self, token: str = getenv("ROBOWEB_API_TOKEN")):
        self.token = token
        self.headers = {"Authorization": f"Token {self.token}"}
        self.session = aiohttp.ClientSession(headers=self.headers)

    async def search_members(self, **kwargs) -> list:
        """
        Search members with given parameters.
        :param kwargs: Supports "discord_id", "real_name", "email_address", "gen", and "warning_points".
        :return:
        """
        url = f"{self.BASE_URL}members/"
        params = {k: v for k, v in kwargs.items() if v is not None}
        async with self.session.get(url, params=params) as response:
            print(response.url)
            if response.status != 200:
                raise Exception(f"Failed to search members: {response.status} ({await response.text()})")
            return await response.json()

    async def index_members(self):
        url = f"{self.BASE_URL}members/"
        members = []
        async with self.session.get(url) as response:
            if response.status != 200:
                raise Exception(f"Failed to index members: {response.status} ({await response.text()})")
            members = await response.json()
        with open("members_index.json", "w", encoding="utf-8") as f:
            dump(members, f, ensure_ascii=False, indent=4)
        return members

    async def get_member_info(self, pk: int, from_index: bool = False) -> dict:
        if from_index:
            with open("members_index.json", "r", encoding="utf-8") as f:
                members = load(f)
            for member in members:
                if member["id"] == pk:
                    return member
        url = f"{self.BASE_URL}members/{pk}/"
        async with self.session.get(url) as response:
            if response.status != 200:
                raise Exception(f"Failed to fetch member info: {response.status} ({await response.text()})")
            return await response.json()

    async def get_bad_guys(self) -> list:
        url = f"{self.BASE_URL}members/bad_guys/"
        async with self.session.get(url) as response:
            if response.status != 200:
                raise Exception(f"Failed to fetch bad guys: {response.status} ({await response.text()})")
            return await response.json()

    async def create_member(self, discord_id: int, real_name: str, gen: int, email_address: str = None) -> dict:
        url = f"{self.BASE_URL}members/"
        payload = {
            "discord_id": str(discord_id),
            "real_name": real_name,
            "gen": gen,
            "email_address": email_address
        }
        async with self.session.post(url, json=payload) as response:
            if response.status != 201:
                raise Exception(f"Failed to create member: {response.status} ({await response.text()})")
            return await response.json()

    async def get_meeting_info(self, meeting_id: int) -> dict:
        url = f"{self.BASE_URL}meetings/{meeting_id}/"
        async with self.session.get(url) as response:
            if response.status != 200:
                raise Exception(f"Failed to fetch meeting info: {response.status} ({await response.text()})")
            return await response.json()

    async def get_upcoming_meetings(self) -> list[dict]:
        url = f"{self.BASE_URL}meetings/upcoming/"
        async with self.session.get(url) as response:
            if response.status != 200:
                raise Exception(f"Failed to fetch upcoming meetings: {response.status} ({await response.text()})")
            return await response.json()

    async def get_absent_requests(self, meeting_id: int) -> list:
        url = f"{self.BASE_URL}absent_requests/?meeting__id={meeting_id}"
        async with self.session.get(url) as response:
            if response.status != 200:
                raise Exception(f"Failed to fetch absent requests: {response.status} ({await response.text()})")
            return await response.json()

    async def create_absent_request(self, meeting_id: int, member_id: int, reason: str):
        url = f"{self.BASE_URL}absent_requests/"
        payload = {
            "meeting": meeting_id,
            "member": member_id,
            "reason": reason,
        }
        async with self.session.post(url, json=payload) as response:
            if response.status != 201:
                raise Exception(f"Failed to create absent request: {response.status} ({await response.text()})")
            return await response.json()

    async def get_pinned_announcements(self) -> list:
        url = f"{self.BASE_URL}announcements/pinned/"
        async with self.session.get(url) as response:
            if response.status != 200:
                raise Exception(f"Failed to fetch pinned announcements: {response.status} ({await response.text()})")
            return await response.json()


if __name__ == "__main__":
    from dotenv import load_dotenv
    from os import getenv
    from pprint import pprint
    import asyncio

    async def main():
        load_dotenv("TOKEN.env")
        api = RobowebAPI(getenv("ROBOWEB_API_TOKEN"))
        # await api.index_members()
        pprint(await api.get_pinned_announcements())
        await api.session.close()

    asyncio.run(main())
