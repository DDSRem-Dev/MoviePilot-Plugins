__all__ = ["AutomatonUtils"]


from ahocorasick import Automaton


class AutomatonUtils:
    """
    Aho-Corasick 工具
    """

    @staticmethod
    def build_automaton(value) -> Automaton:
        """
        构建并返回 Aho-Corasick 自动机

        :param value (List): 关键词列表

        :return Automaton: 构建完成的自动机实例
        """
        a = Automaton()
        if not value:
            a.make_automaton()
            return a
        for keyword in value:
            if keyword:
                a.add_word(keyword.lower(), (keyword, keyword.lower()))
        a.make_automaton()
        return a
