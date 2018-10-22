import time
from django.shortcuts import redirect
from datetime import datetime
from rest_framework.views import APIView
from pay_demo.utils.alipay import AliPay, AlipayAuthorization
from config.settings.base import APP_PRIVATE_KEY, ALIPAY_PUBLIC_KEY, APP_NOTIFY_URL, RETURN_URL, APPID
from django.conf import settings
from rest_framework.response import Response
from rest_framework import mixins, viewsets

from .models import OrderInfo

from .serializers import OrderSerializer
from pay_demo.utils.wechat import WXPay
from pay_demo.utils.utils import xml_to_dict


class OrderViewset(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, mixins.DestroyModelMixin,
                   viewsets.GenericViewSet):
    """
    订单管理
    list:
        获取个人订单
    delete:
        删除订单
    create：
        新增订单
    """
    serializer_class = OrderSerializer

    def get_queryset(self):
        return OrderInfo.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        return OrderSerializer

    def perform_create(self, serializer):
        order = serializer.save()
        return order


class ZhiMaFenView(APIView):

    def get(self, request):
        """
        获取芝麻分
        :param request:
        :return:
        """
        # 判断用户是否有已经授权
        processed_dict = {}
        for key, value in request.GET.items():
            processed_dict[key] = value
        print(processed_dict)
        if "app_auth_code" in processed_dict:
            self.request.user.app_auth_code = processed_dict['app_auth_code']
            self.request.user.save()
            redirect_uri = self.get_zhimafen()
            message = "刚授权"
        elif self.request.user.app_auth_code:
            redirect_uri = self.get_zhimafen()
            message = "以前授权"
        else:
            authorization = AlipayAuthorization(
                appid=APPID,
                redirect_uri=self.request.get_raw_uri(),
                debug=settings.DEBUG,
            )
            redirect_uri = authorization.direct_get_url()
            message = "开始授权"

        return Response({"redirect_uri": redirect_uri, "message": message})

    def get_zhimafen(self):

        alipay = AliPay(
            appid=APPID,
            app_notify_url='',
            app_private_key_path=APP_PRIVATE_KEY,
            alipay_public_key_path=ALIPAY_PUBLIC_KEY,  # 支付宝的公钥，验证支付宝回传消息使用，不是你自己的公钥,
            debug=settings.DEBUG,  # 默认False,
            return_url=''
        )

        url = alipay.get_mayifen(
            self.generate_transaction_id(),
            self.request.user.app_auth_code,
        )
        return alipay.get_gateway(url)

    def generate_transaction_id(self):
        # 当前时间+userid+随机数
        from random import Random
        random_ins = Random()
        transaction_id = "{time_str}{userid}{ranstr}".format(time_str=time.strftime("%Y%m%d%H%M%S"),
                                                             userid=self.request.user.id,
                                                             ranstr=random_ins.randint(10, 99))

        return transaction_id


zhimafen_view = ZhiMaFenView.as_view()


class AlipayView(APIView):

    def get(self, request):
        """
        处理支付宝的return_url返回
        :param request:
        :return:
        """
        processed_dict = {}
        for key, value in request.GET.items():
            processed_dict[key] = value
        sign = processed_dict.pop("sign", None)

        alipay = AliPay(
            appid=APPID,
            app_notify_url=APP_NOTIFY_URL,
            app_private_key_path=APP_PRIVATE_KEY,
            alipay_public_key_path=ALIPAY_PUBLIC_KEY,  # 支付宝的公钥，验证支付宝回传消息使用，不是你自己的公钥,
            debug=settings.DEBUG,  # 默认False,
            return_url=RETURN_URL
        )
        verify_re = alipay.verify(processed_dict, sign)
        if verify_re is True:
            order_sn = processed_dict.get('out_trade_no', None)
            trade_no = processed_dict.get('trade_no', None)
            order_mount = processed_dict.get('total_amount', None)
            seller_id = processed_dict.get('seller_id', None)  # 款支付宝账号对应的支付宝唯一用户号

            existed_orders = OrderInfo.objects.filter(order_sn=order_sn)
            for existed_order in existed_orders:
                existed_order.seller_id = seller_id
                existed_order.order_mount = order_mount
                existed_order.trade_no = trade_no
                existed_order.pay_time = datetime.now()
                existed_order.save()

            response = redirect("home")
            response.set_cookie("nextPath", "pay", max_age=3)
            return response
        else:
            response = redirect("home")
            return response

    def post(self, request):
        """
        处理支付宝的notify_url  一部通知会返回支付状态
        :param request:
        :return:
        """
        processed_dict = {}
        for key, value in request.POST.items():
            processed_dict[key] = value

        sign = processed_dict.pop("sign", None)

        alipay = AliPay(
            appid=APPID,
            app_notify_url=APP_NOTIFY_URL,
            app_private_key_path=APP_PRIVATE_KEY,
            alipay_public_key_path=ALIPAY_PUBLIC_KEY,  # 支付宝的公钥，验证支付宝回传消息使用，不是你自己的公钥,
            debug=settings.DEBUG,  # 默认False,
            return_url=RETURN_URL
        )

        verify_re = alipay.verify(processed_dict, sign)

        if verify_re is True:
            order_sn = processed_dict.get('out_trade_no', None)
            trade_no = processed_dict.get('trade_no', None)  # 该交易在支付宝系统中的交易流水号
            trade_status = processed_dict.get('trade_status', None)

            existed_orders = OrderInfo.objects.filter(order_sn=order_sn,order_mount=processed_dict['total_amount'])
            for existed_order in existed_orders:
                order_goods = existed_order.goods.all()
                for order_good in order_goods:
                    goods = order_good.goods
                    goods.sold_num += order_good.goods_num
                    goods.save()
                existed_order.pay_status = trade_status
                existed_order.trade_no = trade_no
                existed_order.pay_time = datetime.now()
                existed_order.save()

            return Response("success")


alipay_view = AlipayView.as_view()


class WXPayView(APIView):
    # 一部通知支付结果
    def post(self,request):
        processed_dict = {}
        for key, value in request.POST.items():
            processed_dict[key] = value
        # 提取签名
        wxpay = WXPay(
            base_url=settings.WXPAY_BASE_URL,
            request_timeout=settings.WXPAY_REQUEST_TIMEOUT,
            appid=settings.WX_APPID,
            mch_id=settings.WXPAY_MCHID,
            pay_key=settings.WXPAY_KEY,
            notify_url=settings.WXPAY_NOTIFY_URL,
            apiclient_cert_path=settings.WXPAY_APICLIENT_CERT_PATH,
            apiclient_key_path=settings.WXPAY_APICLIENT_KEY_PATH,

        )

        if wxpay.check_sign(processed_dict) is True:
            # 验证金额
            order_sn = processed_dict.get('out_trade_no', None)
            trade_no = processed_dict.get('trade_no', None)  # 该交易在支付宝系统中的交易流水号
            trade_status = processed_dict.get('trade_status', None)

            existed_orders = OrderInfo.objects.filter(order_sn=order_sn, order_mount=processed_dict['total_fee'])

            for existed_order in existed_orders:
                order_goods = existed_order.goods.all()
                for order_good in order_goods:
                    goods = order_good.goods
                    goods.sold_num += order_good.goods_num
                    goods.save()
                existed_order.pay_status = trade_status
                existed_order.trade_no = trade_no
                existed_order.pay_time = datetime.now()
                existed_order.save()

        # todo：提取签名、支付金额等，验证签名是否正确、金额是否正确
        # 思路：在前面获取二维码时，生成了一条订单记录，订单应该保存下订单号、签名、金额等信息。在这里，根据回传的订单号查询数据库，得到对应的签名、金额进行验证即可


        # 最后，别忘了应答微信支付平台，防止重复发送数据
        return '''
                    <xml>
                    <return_code><![CDATA[SUCCESS]]></return_code>
                    <return_msg><![CDATA[OK]]></return_msg>
                    </xml>
                    '''





