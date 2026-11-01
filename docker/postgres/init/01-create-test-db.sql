-- Chạy một lần khi volume pgdata còn rỗng (docs/10 §4, ADR-0007).
-- Database cho pytest: mỗi test chạy trong transaction và rollback.
CREATE DATABASE product_buyer_test;
