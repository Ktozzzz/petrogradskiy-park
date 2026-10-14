# -*- coding: utf-8 -*-
"""Резолвер имён: слова-типы («сад», «сквер»…) не должны совпадать с любым объектом.

Регресс к багу: «расстояние от Летнего сада до Таврического сада» обе точки
резолвился в первый сад базы («Геслеровский») — общим оставалось лишь слово
«сад», и score ровно достигал порога 1.5.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ai.resolver import match_score  # noqa: E402

THRESHOLD = 1.5  # порог принятия совпадения в resolver.resolve


def test_common_noun_does_not_match_any_garden():
    """Регресс: «Летний сад» не должен находить «Геслеровский сад»."""
    assert match_score("Летний сад", "Геслеровский сад") < THRESHOLD
    assert match_score("Таврический сад", "Геслеровский сад") < THRESHOLD


def test_declined_generic_only_query_rejected():
    """«сад»/«сада» — тоже только тип объекта."""
    assert match_score("сад", "Геслеровский сад") < THRESHOLD
    assert match_score("Летнего сада", "Геслеровский сад") < THRESHOLD


def test_same_class_words_do_not_cross_match():
    """Тот же принцип для скверов и бульваров (не только для садов)."""
    assert match_score("Летний сквер", "Кропоткинский сквер") < THRESHOLD
    assert match_score("Таврический бульвар", "Графский бульвар") < THRESHOLD


def test_legitimate_declension_matches():
    """Падежные формы настоящего объекта по-прежнему распознаются."""
    assert match_score("Летнего сада", "Летний сад") >= THRESHOLD
    assert match_score("Вяземского сада", "Вяземский сад") >= THRESHOLD
    assert match_score("Летний сад", "Летний сад") >= THRESHOLD
    assert match_score("Кропоткинского сквера", "Кропоткинский сквер") >= THRESHOLD


def test_single_distinctive_word_matches():
    """Одного узнаваемого слова (не типа объекта) достаточно."""
    assert match_score("Вяземский", "Вяземский сад") >= THRESHOLD
    assert match_score("Чкаловского", "Чкаловский проспект") >= THRESHOLD


def test_full_names_beat_type_mismatch():
    """Имя совпадает, тип объекта другой — сопоставление возможно по имени."""
    assert match_score("Летнего", "Летний сад") >= THRESHOLD
