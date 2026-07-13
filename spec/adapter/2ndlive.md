  好的，采用两个互斥的中间基类方案：

    设计

    协议层提供两个中间基类：

    class RealServiceLive(ProjectLive):
        """真实服务项目继承这个类。
     
        deliver_real 是 @abstractmethod（必须实现）。
        deliver_provided 有默认实现（raise NotImplementedError）。
        """

        @abstractmethod
        def deliver_real(self, request: LiveRequest) -> Any:
            """调用业务系统拿 raw_response。项目必须实现。"""
            pass

        def deliver_provided(self, case, request: LiveRequest) -> Any:
            """provided 模式：真实服务项目不需要覆盖。"""
            raise NotImplementedError(...)


    class ProvidedOutputLive(ProjectLive):
        """provided-output 项目继承这个类。
     
        deliver_provided 是 @abstractmethod（必须实现）。
        deliver_real 有默认实现（raise NotImplementedError）。
        """

        def deliver_real(self, request: LiveRequest) -> Any:
            """real 模式：provided-output 项目不需要覆盖。"""
            raise NotImplementedError(...)

        @abstractmethod
        def deliver_provided(self, case, request: LiveRequest) -> Any:
            """从 case.output 拿 raw_response。项目必须实现。"""
            pass

    效果

    - 新项目接入时选一个继承 → abstractmethod 明确指导该实现哪个
      - class ClientSearchLive(RealServiceLive) → 知道要实现 deliver_real
      - class QALive(ProvidedOutputLive) → 知道要实现 deliver_provided
    - abstractmethod 约束匹配：只约束该实现的那一个，不强制实现互斥的另一个
    - 运行时走错分支报错：走错类型的方法默认 raise
    - 协议层 deliver 保持 @final：统一 dispatch（根据 ready 协议决定走 deliver_real 还是 deliver_provided）