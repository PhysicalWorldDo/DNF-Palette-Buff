import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.mod_buff import BUFF_DATA


EXPECTED_BUFF_EXPORTS = {
    "鬼剑士": {
        "阿修罗": "01_ghost_M_buf_asura",
        "狂战士": "01_ghost_M_buf_bsk",
        "剑影": "01_ghost_M_buf_ghost",
        "鬼泣": "01_ghost_M_buf_soul",
        "剑魂": "01_ghost_M_buf_wep",
        "刃影": "02_ghost_F_buf_blade",
        "剑魔": "02_ghost_F_buf_demon",
        "暗帝": "02_ghost_F_buf_darktemp",
        "剑宗": "02_ghost_F_buf_sword",
        "剑帝": "02_ghost_F_buf_vega",
    },
    "格斗家": {
        "柔道家(女)": "04_fighter_F_buf_grap",
        "气功师(女)": "04_fighter_F_buf_nen",
        "街霸(女)": "04_fighter_F_buf_street",
        "散打(女)": "04_fighter_F_buf_strik",
        "柔道家(男)": "03_figher_M_buf_grap",
        "气功师(男)": "03_figher_M_buf_nen",
        "街霸(男)": "03_figher_M_buf_Street",
        "散打(男)": "03_figher_M_buf_strik",
    },
    "魔法师": {
        "血法师": "07_mage_M_buf_bloodm",
        "次元行者": "07_mage_M_buf_dimension",
        "元素爆破师": "07_mage_M_buf_elbomber",
        "冰结师": "07_mage_M_buf_glancial",
        "逐风者": "07_mage_M_buf_swiftma",
        "战斗法师": "08_mage_F_buf_battlemage",
        "元素师": "08_mage_F_buf_element",
        "小魔女": "08_mage_F_buf_enchant",
        "召唤师": "08_mage_F_buf_summoner",
        "魔道学者": "08_mage_F_buf_witch",
    },
    "神枪手": {
        "合金战士": "05_gunner_M_buf_assult",
        "枪炮师(男)": "05_gunner_M_buf_luncher",
        "机械师(男)": "05_gunner_M_buf_meca",
        "漫游枪手(男)": "05_gunner_M_buf_ranger",
        "弹药专家(男)": "05_gunner_M_buf_spit",
        "枪炮师(女)": "06_gunner_F_buf_launcher",
        "机械师(女)": "06_gunner_F_buf_meca",
        "漫游枪手(女)": "06_gunner_F_buf_ranger",
        "弹药专家(女)": "06_gunner_F_buf_spit",
        "协战师": "06_gunner_F_buf_paramedic",
    },
    "圣职者": {
        "复仇者": "09_prist_M_buf_avenger",
        "圣骑士(审判)": "09_prist_M_buf_battlecru",
        "圣骑士(奶爸)": "09_prist_M_buf_buffcru",
        "驱魔师": "09_prist_M_buf_exorcist",
        "蓝拳圣使(男)": "09_prist_M_buf_infight",
        "巫女": "10_priest_F_buf_sorcer",
        "圣骑士(女)": "10_priest_F_buf_crusager",
        "异端审判者": "10_priest_F_buf_inquis",
        "诱魔者": "10_priest_F_buf_mistress",
        "蓝拳圣使(女)": "10_priest_F_buf_infigh",
    },
    "暗夜": {
        "暗夜使者": "11_thief_buf_necro",
        "刺客": "11_thief_buf_rogue",
        "忍者": "11_thief_buf_kuno",
        "影舞者": "11_thief_buf_shadow",
    },
    "魔枪士": {
        "暗枪士": "14_demolancer_buf_darklancer",
        "狩猎者": "14_demolancer_buf_dralancer",
        "决战者": "14_demolancer_buf_duelist",
        "征战者": "14_demolancer_buf_vanguard",
    },
    "守护者": {
        "混沌魔灵": "12_knight_buf_chaos",
        "龙骑士": "12_knight_buf_dragonkn",
        "精灵骑士": "12_knight_buf_eleven",
        "帕拉丁": "12_knight_buf_paladin",
    },
    "枪剑士": {
        "特工": "15_GunBla_buf_agent",
        "暗刃": "15_GunBla_buf_hitman",
        "源能专家": "15_GunBla_buf_specilist",
        "战线佣兵": "15_GunBla_buf_trouble",
    },
    "弓箭手": {
        "猎人": "16_archer_buf_hunter",
        "妖护使": "16_archer_buf_vigil",
        "缪斯": "16_archer_buf_muse",
        "旅人": "16_archer_buf_traveler",
        "奇美拉": "16_archer_buf_chimera",
    },
    "外传": {
        "黑暗武士": "13_ECT_darkknight_buf",
        "缔造者": "13_ECT_Creater_buf",
    },
    "帝国骑士": {
        "破浪者": "17_imperial_F_buf_break",
    },
}


class BuffMappingTest(unittest.TestCase):
    def test_buff_exports_match_new_bk2_names(self):
        self.assertEqual(BUFF_DATA, EXPECTED_BUFF_EXPORTS)

    def test_export_codes_are_stems_without_bk2_extension(self):
        for jobs in BUFF_DATA.values():
            for code in jobs.values():
                self.assertFalse(code.lower().endswith(".bk2"), code)


if __name__ == "__main__":
    unittest.main()
