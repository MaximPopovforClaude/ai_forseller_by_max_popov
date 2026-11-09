import asyncio
import json


class RPCError(RuntimeError):
    pass


class AppServer:
    def __init__(self, command, on_notification=None, on_request=None, env=None):
        self.command = command
        self.env = env
        self.on_notification = on_notification
        self.on_request = on_request
        self.pending = {}
        self.tasks = set()
        self.next_id = 1
        self.process = None

    async def start(self, cwd):
        self.process = await asyncio.create_subprocess_exec(*self.command, cwd=cwd, env=self.env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=64*1024*1024)
        self.reader = asyncio.create_task(self.read())
        await self.call('initialize', {'clientInfo': {'name':'personal_platform', 'title':'AI-100metric', 'version':'1.0.0'},
            'capabilities': {'experimentalApi':True}})
        await self.send({'method':'initialized', 'params':{}})

    async def send(self, data):
        self.process.stdin.write(json.dumps(data, ensure_ascii=False).encode() + b'\n')
        await self.process.stdin.drain()

    async def call(self, method, params, timeout=90):
        ident = self.next_id
        self.next_id += 1
        future = asyncio.get_running_loop().create_future()
        self.pending[ident] = future
        try:
            await self.send({'id':ident, 'method':method, 'params':params})
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(ident, None)

    async def handle_request(self, data):
        try:
            if self.on_request is None:
                raise RPCError('No request handler')
            result = await self.on_request(data['method'], data.get('params', {}))
            await self.send({'id':data['id'], 'result':result})
        except Exception:
            # Do not expose transport URLs or credentials through exception text.
            await self.send({'id':data['id'], 'error':{'code':-32603, 'message':'Request failed safely'}})

    async def read(self):
        try:
            while raw := await self.process.stdout.readline():
                data = json.loads(raw)
                if 'id' in data and 'method' in data:
                    task = asyncio.create_task(self.handle_request(data))
                    self.tasks.add(task)
                    task.add_done_callback(self.tasks.discard)
                elif 'id' in data:
                    future = self.pending.get(data['id'])
                    if future and not future.done():
                        if 'error' in data:
                            future.set_exception(RPCError(json.dumps(data['error'], ensure_ascii=False)))
                        else:
                            future.set_result(data.get('result'))
                elif self.on_notification:
                    await self.on_notification(data.get('method', ''), data.get('params', {}))
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(RPCError('Codex process disconnected'))

    async def wait_closed(self):
        """A dead event reader is fatal even after turn/start has returned."""
        try:
            await asyncio.shield(self.reader)
        except Exception:
            raise RPCError('Codex event stream failed') from None
        raise RPCError('Codex event stream closed')

    async def close(self):
        for task in self.tasks:
            task.cancel()
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 10)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        if hasattr(self, 'reader'):
            await asyncio.gather(self.reader, return_exceptions=True)
