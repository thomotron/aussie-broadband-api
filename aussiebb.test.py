import unittest

from aussiebb import AussieBB


class AussieBB_Tests(unittest.TestCase):
    def init_useDefaults_successful(self):
        abb = AussieBB()
        self.assertIsNotNone(AussieBB())

    def init_customCacheRefreshDuration_successful(self):
        abb1 = AussieBB(cache_refresh=0)
        abb2 = AussieBB(cache_refresh=1)
        abb3 = AussieBB(cache_refresh=5)
        abb4 = AussieBB(cache_refresh=123456)
        abb5 = AussieBB(cache_refresh=99999999999999999999999999999999999999999999999999999999999999999999999)

        self.assertIsNotNone(abb1)
        self.assertIsNotNone(abb2)
        self.assertIsNotNone(abb3)
        self.assertIsNotNone(abb4)
        self.assertIsNotNone(abb5)

        self.assertEquals(abb1.cache_refresh, 0)
        self.assertEquals(abb2.cache_refresh, 1)
        self.assertEquals(abb3.cache_refresh, 5)
        self.assertEquals(abb4.cache_refresh, 123456)
        self.assertEquals(abb5.cache_refresh, 99999999999999999999999999999999999999999999999999999999999999999999999)



if __name__ == '__main__':
    unittest.main()
