import struct

import os
from enum import Enum

from twisted.internet.protocol import Protocol
from client import kProccessState
from client import Client
from common import MAX_PACKET_SIZE, cal_file_hash
from mylog import xtrace, SOCKET_OUT, SOCKET_IN, log
from remote.remote_control import remove_from_alive

HEAD_FORMAT = "!3sI"
HEAD_SIZE = 7


class kTransFileState(Enum):
    kNeedFileHash = 10001
    kNoFile = 10002
    kSendFail = 10004


# 这个类类似于muduo中的TcpConnection
class UserProtocol(Protocol):
    def __init__(self, factory, addr):
        self.factory = factory
        self.client = Client(addr)
        self.transfile_state = kTransFileState.kNoFile
        self.recv_file_name = None

    # 主动关闭套接字
    def end_connection(self):
        self.transport.loseConnection()

    # 当一个客户端连接到来的时候
    # newConnectionCallBack()
    def send_info(self, kind, info):
        if info == "":
            return 0
        # assert self.__connected
        xtrace("%s [%s] %s %s" % (SOCKET_OUT, self.client.get_user_no(), kind, info))

        buf = info.encode()
        rest_size = len(buf)
        buf = struct.pack(HEAD_FORMAT, kind.encode(), rest_size) + buf
        self.transport.write(buf)

    def reply_client(self):
        responses = self.client.get_response().split('\n')
        for response in responses:
            self.send_info("RPL", response)

    def ctl_client(self):
        self.send_info("CTL", self.client.get_response())

    def connectionMade(self):
        # 发送认证消息
        self.send_info("ATH", "WHO ARE YOU")

    # 当一个客户端连接关闭的时候
    # clientCloseCallBack()

    def get_host(self):
        self.transport.getHost()

    def connectionLost(self, reason):
        self.client.client_offline()
        print("a connection closed" + str(self.client.get_user_no()))
    #   self.factory.delete_client(self)

    # clientReadCallBack()
    def dataReceived(self, data):
        print(data)
        # 定义一个状态机来做协议解析
        cmd, cmd_info = self.do_parse_request(data)
        xtrace("%s [%s] %s %s" % (SOCKET_IN, self.client.get_user_no(), cmd, cmd_info))
        # 当发送完文件Hash之后，获取到客户端的回复（客户端是否存在文件），继而发送文件
        if self.transfile_state == kTransFileState.kNeedFileHash:
            self.send_file(self.client.get_kw_filename(), cmd_info)
            return

        result = self.client.process_cmd(cmd, cmd_info)

        # 业务逻辑处理完之后将处理结果发送给客户端
        # if result == kProccessState.kRemoteCtl:
        #    self.ctl_client()
        # else:
        self.reply_client()

        # 根据处理结果做点事情
        # 如果处理结果是认证失败或需关闭与客户端连接
        if result == kProccessState.kAuthFail or result == kProccessState.kEndConnecion:
            self.end_connection()
            # 成功写入关键字文件，需要network接口层发送文件
        elif result == kProccessState.kMakeKwSuccess:
            self.send_file(self.client.get_kw_filename())

    def do_parse_request(self, recv_data):
        # parse request
        rpl = None
        rest_pkt_size = None
        # recv_data_len = len(recv_data)
        try:
            rpl, rest_pkt_size = struct.unpack(HEAD_FORMAT, recv_data[:HEAD_SIZE])
        except Exception as error:
            print(error)
        cmd = rpl.decode()

        cmd_info = recv_data[HEAD_SIZE:HEAD_SIZE + rest_pkt_size].decode()
        return cmd, cmd_info

    def send_file(self, local_file, info=None):
        # 首先发送关键字列表的文件哈希
        user_no = self.client.get_user_no()
        if self.transfile_state == kTransFileState.kNoFile:
            self.send_info("RPL", cal_file_hash(local_file))
            self.transfile_state = kTransFileState.kNeedFileHash
        else:
            # 已发送完文件hash，客户端文件存在则不需要发送
            if "EXISTED" == info:
                log("%s KEYWORDS IS UP-TO-DATE" % user_no)
                self.transfile_state = kTransFileState.kNoFile
            else:
                file_size = os.path.getsize(local_file)
                # 发送文件大小
                self.send_info("RPL", str(file_size))
                rest_size = file_size
                fp = open(local_file, 'rb')
                flag = 0
                while rest_size:
                    buf = fp.read(MAX_PACKET_SIZE)
                    try:
                        self.transport.write(buf)
                        rest_size -= len(buf)

                    except Exception as error:
                        print(error)
                        flag = 1
                        break
                fp.close()
                if flag == 1:
                    self.transfile_state = kTransFileState.kSendFail
                    return False
                log("send Keywords Done")

            self.transfile_state = kTransFileState.kNoFile

        return True

    def is_connected(self):
        return self.transport.connected
